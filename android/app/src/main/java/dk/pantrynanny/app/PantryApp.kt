package dk.pantrynanny.app

import android.app.Application
import androidx.room.Room
import dk.pantrynanny.app.data.CacheWriter
import dk.pantrynanny.app.data.ImageRepository
import dk.pantrynanny.app.data.InventoryRepository
import dk.pantrynanny.app.data.NetworkMonitor
import dk.pantrynanny.app.data.ScanRepository
import dk.pantrynanny.app.data.SettingsStore
import dk.pantrynanny.app.data.SyncRepository
import dk.pantrynanny.app.data.TokenStore
import dk.pantrynanny.app.data.local.AppDatabase
import dk.pantrynanny.app.data.remote.ApiClient
import dk.pantrynanny.app.sync.SyncScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class PantryApp : Application() {
    /** Lazy + thread-safe: WorkManager workers may touch it before/while onCreate runs. */
    val container: AppContainer by lazy(LazyThreadSafetyMode.SYNCHRONIZED) { AppContainer(this) }

    override fun onCreate() {
        super.onCreate()
        container.start()
    }
}

/** Manual dependency injection: one instance of everything, created in [PantryApp]. */
class AppContainer(val app: Application) {
    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    val db: AppDatabase = Room.databaseBuilder(app, AppDatabase::class.java, "pantrynanny.db").build()
    val settings = SettingsStore(app)
    val tokens = TokenStore(app)
    val api = ApiClient(settings, tokens, imageCacheDir = java.io.File(app.cacheDir, "images"))
    val images = ImageRepository(api)
    val cache = CacheWriter(db)
    val syncRepository = SyncRepository(db, api, settings, tokens, cache)
    val scanRepository = ScanRepository(db)
    val inventoryRepository = InventoryRepository(api, cache)
    val network = NetworkMonitor(app)
    val scheduler = SyncScheduler(app)

    private val syncTrigger = Channel<Unit>(Channel.CONFLATED)

    fun start() {
        // Debounced foreground sync: a burst of scans is uploaded as one batch ~1.5 s after the last scan.
        appScope.launch {
            for (ignored in syncTrigger) {
                delay(1500)
                syncTrigger.tryReceive() // collapse triggers that arrived during the delay
                syncRepository.syncNow()
            }
        }
        scheduler.schedulePeriodic()
        network.start { if (tokens.token() != null) requestSync() }
        if (tokens.token() != null) requestSync()
    }

    /** Called after every scan / edit / connectivity change. Never blocks the caller. */
    fun requestSync() {
        if (tokens.token() == null) return
        scheduler.enqueueOneTime()
        syncTrigger.trySend(Unit)
    }

    fun syncNowManually() {
        appScope.launch { syncRepository.syncNow(forcePull = true) }
    }

    /** First sync after login: always starts from a fresh snapshot. */
    fun onLoggedIn() {
        appScope.launch {
            settings.setCursor(null)
            scheduler.schedulePeriodic()
            syncRepository.syncNow(forcePull = true)
        }
    }

    /** Revokes the token (best effort), clears every local table - including queued ops. */
    suspend fun logout() {
        api.logout()
        tokens.clear()
        scheduler.cancelAll()
        wipeLocalData()
        settings.setUserLabel(null)
    }

    /** Clears the cache, queued ops and history. Waits for any running sync first (sync mutex). */
    suspend fun wipeLocalData() {
        syncRepository.exclusive {
            settings.setCursor(null)
            settings.setCacheOwner(null)
            withContext(Dispatchers.IO) { db.clearAllTables() }
        }
    }

    val isDebuggable: Boolean
        get() = (app.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0
}
