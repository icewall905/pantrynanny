package dk.pantrynanny.app.data

import androidx.room.withTransaction
import dk.pantrynanny.app.data.local.AppDatabase
import dk.pantrynanny.app.data.local.PendingOpEntity
import dk.pantrynanny.app.data.remote.ApiClient
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.OpResultDto
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

enum class SyncOutcome { SUCCESS, RETRY, AUTH_FAILED, FAILED, NOT_LOGGED_IN }

/**
 * Upload pending ops in order (batches of up to [BATCH_SIZE]), then pull server state
 * (snapshot on first run, afterwards /sync/changes?since=cursor). Ops are never dropped:
 * on any failure they go back to `pending`; ops the server rejects are kept as `rejected`.
 * A mutex serialises concurrent callers (foreground debounce, WorkManager, manual).
 */
class SyncRepository(
    private val db: AppDatabase,
    private val api: ApiClient,
    private val settings: SettingsStore,
    private val tokens: TokenStore,
    private val cache: CacheWriter,
) {
    private val mutex = Mutex()
    private var forcePullNext = false // guarded by mutex

    /** Run [block] while no sync can run (used before wiping the local database). */
    suspend fun <T> exclusive(block: suspend () -> T): T = mutex.withLock { block() }

    private val _syncing = MutableStateFlow(false)
    val syncing: StateFlow<Boolean> = _syncing

    private val _lastError = MutableStateFlow<String?>(null)
    /** Non-null when the last sync attempt failed (server unreachable, etc.). */
    val lastError: StateFlow<String?> = _lastError

    suspend fun syncNow(forcePull: Boolean = false): SyncOutcome = mutex.withLock {
        if (tokens.token() == null) return@withLock SyncOutcome.NOT_LOGGED_IN
        _syncing.value = true
        try {
            doSync(forcePull)
        } finally {
            _syncing.value = false
        }
    }

    private suspend fun doSync(forcePull: Boolean): SyncOutcome {
        db.pendingOpDao().resetInflight()
        val push = pushAll()
        if (push != SyncOutcome.SUCCESS) return push
        val s = settings.current()
        val now = System.currentTimeMillis()
        if (forcePull || forcePullNext || s.syncCursor == null || now - s.lastPullAtMs > PULL_THROTTLE_MS) {
            val pull = pull(s.syncCursor)
            if (pull != SyncOutcome.SUCCESS) return pull
            forcePullNext = false
        }
        _lastError.value = null
        return SyncOutcome.SUCCESS
    }

    // ---- Push ------------------------------------------------------------------------------

    private suspend fun pushAll(): SyncOutcome {
        val opDao = db.pendingOpDao()
        val deviceId = settings.ensureDeviceId()
        var batchSize = BATCH_SIZE
        while (true) {
            // Claim atomically: select + mark inflight in one transaction, then send only rows
            // that are really inflight (an undo may have deleted a pending op in between).
            val batch = db.withTransaction {
                val candidates = opDao.nextPending(batchSize)
                if (candidates.isEmpty()) {
                    emptyList<PendingOpEntity>()
                } else {
                    val ids = candidates.map { it.seq }
                    opDao.markInflight(ids)
                    opDao.getInflight(ids)
                }
            }
            if (batch.isEmpty()) return SyncOutcome.SUCCESS
            val seqs = batch.map { it.seq }
            when (val r = api.postOps(deviceId, batch.map { it.toDto() })) {
                is ApiResult.Ok -> {
                    val byId = r.value.results.associateBy { it.clientOpId }
                    if (applyResults(batch, byId)) forcePullNext = true
                    val missing = batch.filter { it.clientOpId !in byId }
                    if (missing.isNotEmpty()) {
                        opDao.revertToPending(missing.map { it.seq })
                        _lastError.value = "Incomplete server response"
                        return SyncOutcome.RETRY
                    }
                    if (batchSize == 1) batchSize = BATCH_SIZE
                }
                is ApiResult.NetworkError -> {
                    opDao.revertToPending(seqs)
                    _lastError.value = r.cause.message ?: "Network error"
                    return SyncOutcome.RETRY
                }
                is ApiResult.HttpError -> {
                    opDao.revertToPending(seqs)
                    if (r.code == 401) return authFailed()
                    if (r.code == 408 || r.code == 429 || r.code >= 500) {
                        _lastError.value = "HTTP ${r.code}"
                        return SyncOutcome.RETRY
                    }
                    if (batch.size > 1) {
                        batchSize = 1 // isolate the offending op
                    } else {
                        opDao.markRejected(batch[0].clientOpId, "HTTP ${r.code}: ${r.detail ?: ""}".trim())
                    }
                }
            }
        }
    }

    /** Returns true when an applied op came back without a product although it targeted one (then we pull). */
    private suspend fun applyResults(batch: List<PendingOpEntity>, byId: Map<String, OpResultDto>): Boolean {
        var needPull = false
        db.withTransaction {
            for (op in batch) {
                val res = byId[op.clientOpId] ?: continue
                if (res.status == "applied" || res.status == "duplicate") {
                    val product = res.product
                    if (product != null) {
                        cache.applyProduct(product, res.totalQuantity)
                        db.historyDao().attachProduct(op.clientOpId, product.id, product.name)
                    } else if (op.productId != null) {
                        needPull = true
                    }
                    db.pendingOpDao().deleteByClientOpId(op.clientOpId)
                } else {
                    db.pendingOpDao().markRejected(op.clientOpId, res.error ?: res.errorCode ?: res.status)
                }
            }
        }
        return needPull
    }

    // ---- Pull ------------------------------------------------------------------------------

    private suspend fun pull(cursor: String?): SyncOutcome {
        if (cursor == null) return fullSnapshot()
        return when (val r = api.changes(cursor)) {
            is ApiResult.Ok -> {
                val c = r.value
                if (c.fullResyncRequired) {
                    fullSnapshot()
                } else {
                    cache.applyChanges(c)
                    if (c.cursor.isNotEmpty()) settings.setCursor(c.cursor)
                    settings.setLastPull(System.currentTimeMillis())
                    SyncOutcome.SUCCESS
                }
            }
            else -> mapError(r)
        }
    }

    private suspend fun fullSnapshot(): SyncOutcome =
        when (val r = api.snapshot()) {
            is ApiResult.Ok -> {
                val s = r.value
                cache.applySnapshot(s)
                s.settings?.let { settings.setServerSettings(it.scanRearmMs, it.removeModeTimeoutMin) }
                settings.setCursor(s.cursor.ifEmpty { null })
                settings.setLastPull(System.currentTimeMillis())
                SyncOutcome.SUCCESS
            }
            else -> mapError(r)
        }

    private fun mapError(r: ApiResult<*>): SyncOutcome = when (r) {
        is ApiResult.Ok -> SyncOutcome.SUCCESS
        is ApiResult.NetworkError -> {
            _lastError.value = r.cause.message ?: "Network error"
            SyncOutcome.RETRY
        }
        is ApiResult.HttpError -> when {
            r.code == 401 -> authFailed()
            r.code == 408 || r.code == 429 || r.code >= 500 -> {
                _lastError.value = "HTTP ${r.code}"
                SyncOutcome.RETRY
            }
            else -> {
                _lastError.value = "HTTP ${r.code}: ${r.detail ?: ""}"
                SyncOutcome.FAILED
            }
        }
    }

    /** Token rejected: drop it (UI goes to login) but keep every local op and the cache. */
    private fun authFailed(): SyncOutcome {
        tokens.clear()
        _lastError.value = "Unauthorized"
        return SyncOutcome.AUTH_FAILED
    }

    private companion object {
        const val BATCH_SIZE = 100
        const val PULL_THROTTLE_MS = 10_000L
    }
}
