package dk.pantrynanny.app.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dk.pantrynanny.app.domain.ScanDeduplicator
import dk.pantrynanny.app.domain.ScanMode
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.util.UUID

const val DEFAULT_SERVER_URL = ""

data class AppSettings(
    val serverUrl: String = DEFAULT_SERVER_URL,
    val deviceId: String? = null,
    val mode: ScanMode = ScanMode.ADD,
    val sound: Boolean = true,
    val vibrate: Boolean = true,
    val defaultLocationId: String? = null,
    /** User override; null = use the household setting from the server. */
    val rearmMsOverride: Int? = null,
    val syncCursor: String? = null,
    val serverRearmMs: Int = ScanDeduplicator.DEFAULT_REARM_MS.toInt(),
    val serverRemoveTimeoutMin: Int = 10,
    val userLabel: String? = null,
    val lastPullAtMs: Long = 0L,
    /** "serverUrl|householdId" the local database belongs to. */
    val cacheOwner: String? = null,
) {
    val effectiveRearmMs: Int
        get() = (rearmMsOverride ?: serverRearmMs)
            .coerceIn(ScanDeduplicator.MIN_REARM_MS.toInt(), ScanDeduplicator.MAX_REARM_MS.toInt())
}

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "settings")

class SettingsStore(private val context: Context) {
    private object Keys {
        val serverUrl = stringPreferencesKey("server_url")
        val deviceId = stringPreferencesKey("device_id")
        val mode = stringPreferencesKey("scan_mode")
        val sound = booleanPreferencesKey("sound")
        val vibrate = booleanPreferencesKey("vibrate")
        val defaultLocation = stringPreferencesKey("default_location")
        val rearm = intPreferencesKey("rearm_ms")
        val cursor = stringPreferencesKey("sync_cursor")
        val serverRearm = intPreferencesKey("server_rearm_ms")
        val serverTimeout = intPreferencesKey("server_remove_timeout_min")
        val userLabel = stringPreferencesKey("user_label")
        val lastPull = longPreferencesKey("last_pull_at")
        val cacheOwner = stringPreferencesKey("cache_owner")
    }

    val flow: Flow<AppSettings> = context.dataStore.data.map { p ->
        AppSettings(
            serverUrl = p[Keys.serverUrl] ?: DEFAULT_SERVER_URL,
            deviceId = p[Keys.deviceId],
            mode = ScanMode.fromKey(p[Keys.mode]),
            sound = p[Keys.sound] ?: true,
            vibrate = p[Keys.vibrate] ?: true,
            defaultLocationId = p[Keys.defaultLocation],
            rearmMsOverride = p[Keys.rearm],
            syncCursor = p[Keys.cursor],
            serverRearmMs = p[Keys.serverRearm] ?: ScanDeduplicator.DEFAULT_REARM_MS.toInt(),
            serverRemoveTimeoutMin = p[Keys.serverTimeout] ?: 10,
            userLabel = p[Keys.userLabel],
            lastPullAtMs = p[Keys.lastPull] ?: 0L,
            cacheOwner = p[Keys.cacheOwner],
        )
    }

    suspend fun current(): AppSettings = flow.first()

    /** Stable per-install device id (UUID), created on first use. */
    suspend fun ensureDeviceId(): String {
        current().deviceId?.let { return it }
        var result = ""
        context.dataStore.edit { p ->
            val existing = p[Keys.deviceId]
            if (existing != null) {
                result = existing
            } else {
                result = UUID.randomUUID().toString()
                p[Keys.deviceId] = result
            }
        }
        return result
    }

    suspend fun setServerUrl(url: String) = context.dataStore.edit { it[Keys.serverUrl] = url.trim().trimEnd('/') }
    suspend fun setMode(mode: ScanMode) = context.dataStore.edit { it[Keys.mode] = mode.name.lowercase() }
    suspend fun setSound(on: Boolean) = context.dataStore.edit { it[Keys.sound] = on }
    suspend fun setVibrate(on: Boolean) = context.dataStore.edit { it[Keys.vibrate] = on }
    suspend fun setDefaultLocation(id: String?) = context.dataStore.edit {
        if (id == null) it.remove(Keys.defaultLocation) else it[Keys.defaultLocation] = id
    }

    suspend fun setRearmOverride(ms: Int?) = context.dataStore.edit {
        if (ms == null) it.remove(Keys.rearm) else it[Keys.rearm] = ms
    }

    suspend fun setCursor(cursor: String?) = context.dataStore.edit {
        if (cursor == null) it.remove(Keys.cursor) else it[Keys.cursor] = cursor
    }

    suspend fun setCacheOwner(owner: String?) = context.dataStore.edit {
        if (owner == null) it.remove(Keys.cacheOwner) else it[Keys.cacheOwner] = owner
    }

    suspend fun setLastPull(ms: Long) = context.dataStore.edit { it[Keys.lastPull] = ms }
    suspend fun setUserLabel(label: String?) = context.dataStore.edit {
        if (label == null) it.remove(Keys.userLabel) else it[Keys.userLabel] = label
    }

    suspend fun setServerSettings(rearmMs: Int, removeTimeoutMin: Int) = context.dataStore.edit {
        it[Keys.serverRearm] = rearmMs
        it[Keys.serverTimeout] = removeTimeoutMin
    }
}
