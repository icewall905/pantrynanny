package dk.pantrynanny.app.ui

import android.os.SystemClock
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.AppSettings
import dk.pantrynanny.app.data.UndoResult
import dk.pantrynanny.app.data.local.HistoryRow
import dk.pantrynanny.app.domain.BarcodeNormalizer
import dk.pantrynanny.app.data.LookupOutcome
import dk.pantrynanny.app.domain.CardLookup
import dk.pantrynanny.app.domain.CardPhase
import dk.pantrynanny.app.domain.DecodedBarcode
import dk.pantrynanny.app.domain.LookupTrack
import dk.pantrynanny.app.domain.ModePolicy
import dk.pantrynanny.app.domain.ScanConfirmer
import dk.pantrynanny.app.domain.ScanDeduplicator
import dk.pantrynanny.app.domain.ScanMode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** How long "Registrer" waits for an unsynced unknown scan to come back with its placeholder product. */
private const val REGISTER_WAIT_MS = 10_000L
private const val ALREADY_COUNTED_MS = 2_500L
private const val MAX_WATCHERS = 10
private const val RECHECK_MS = 20_000L

data class SyncStatusUi(
    val pending: Int = 0,
    val rejected: Int = 0,
    val online: Boolean = true,
    val serverProblem: Boolean = false,
    val syncing: Boolean = false,
)

data class ScannerUiState(
    val mode: ScanMode = ScanMode.ADD,
    val torch: Boolean = false,
    val frontCamera: Boolean = false,
    val last: HistoryRow? = null,
    val history: List<HistoryRow> = emptyList(),
    val status: SyncStatusUi = SyncStatusUi(),
    val alreadyCounted: Boolean = false,
    val otherFormats: Boolean = false,
    /** What the last-scanned card shows (neutral while the product is being looked up). */
    val lastPhase: CardPhase = CardPhase.KNOWN,
)

class ScannerViewModel(private val c: AppContainer) : ViewModel() {

    private val settings: StateFlow<AppSettings> =
        c.settings.flow.stateIn(viewModelScope, SharingStarted.Eagerly, AppSettings())

    private val _mode = MutableStateFlow(ScanMode.ADD)
    private val _torch = MutableStateFlow(false)

    private val dedup = ScanDeduplicator(ScanDeduplicator.DEFAULT_REARM_MS) { SystemClock.elapsedRealtime() }
    /** Misread filter in front of [dedup]. */
    private val confirmer = ScanConfirmer { SystemClock.elapsedRealtime() }
    private val _track = MutableStateFlow<LookupTrack?>(null)
    private val currentOpId = MutableStateFlow<String?>(null)
    private val trackCounter = AtomicLong()
    private val guard = c.scanGuard
    private val _already = MutableStateFlow(false)
    private var alreadyJob: Job? = null
    private val feedback = Feedback(c.app)

    @Volatile
    private var lastActivityMs = SystemClock.elapsedRealtime()

    private val _events = MutableSharedFlow<UiMessage>(extraBufferCapacity = 16)
    val events: SharedFlow<UiMessage> = _events.asSharedFlow()

    /** client_op_id of a scan whose barcode is not a known product yet (offer "Registrer"). */
    /**
     * Scans that may be unknown (cache miss or a known placeholder), emitted right after the scan so
     * the screen can grab the camera frame while the item is still in view. If the product turns out
     * to be known and already has a picture, the uploader just discards the frame.
     */
    private val _snapshotRequests = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val snapshotRequests: SharedFlow<String> = _snapshotRequests.asSharedFlow()

    private val _unknownScans = MutableSharedFlow<String>(extraBufferCapacity = 4)
    val unknownScans: SharedFlow<String> = _unknownScans.asSharedFlow()

    /** Product to open in edit mode after the user asked to register an unknown scan. */
    private val _openForRegister = MutableSharedFlow<String>(extraBufferCapacity = 1)
    val openForRegister: SharedFlow<String> = _openForRegister.asSharedFlow()

    private val status = combine(
        c.db.pendingOpDao().observePendingCount(),
        c.db.pendingOpDao().observeRejected().map { it.size },
        c.network.online,
        c.syncRepository.lastError,
        c.syncRepository.syncing,
    ) { pending, rejected, online, error, syncing ->
        SyncStatusUi(pending, rejected, online, error != null, syncing)
    }

    val uiState: StateFlow<ScannerUiState> = combine(
        _mode,
        _torch,
        c.db.historyDao().observeRecent(30),
        status,
        settings.map { it.frontCamera },
    ) { mode, torch, history, st, front ->
        ScannerUiState(mode, torch, front, history.firstOrNull(), history, st)
    }.combine(_already) { s, already -> s.copy(alreadyCounted = already) }
        .combine(settings.map { it.otherBarcodeTypes }) { s, other -> s.copy(otherFormats = other) }
        .combine(_track) { s, track ->
            s.copy(lastPhase = s.last?.let { CardLookup.phase(it.entry.clientOpId, it.prodStatus, track) } ?: CardPhase.KNOWN)
        }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), ScannerUiState())

    init {
        // Cold start: the app always starts in Add mode (a persisted Remove mode is reset).
        viewModelScope.launch {
            c.settings.setMode(ScanMode.ADD)
            // ...unless a launcher shortcut asked for a mode ("Scan out").
            c.requestedMode.collect { m ->
                if (m != null) {
                    c.requestedMode.value = null
                    setMode(m)
                }
            }
        }
        viewModelScope.launch {
            settings.collect { dedup.rearmMs = it.effectiveRearmMs.toLong() }
        }
        viewModelScope.launch {
            while (isActive) {
                delay(15_000)
                revertRemoveIfIdle(clearDedup = true)
            }
        }
    }

    fun setMode(mode: ScanMode) {
        if (_mode.value == mode) return
        applyMode(mode, clearDedup = true)
        touch()
    }

    /** Flip between rear and front camera (remembered); the dedup state belongs to the old view. */
    fun toggleCamera() {
        val front = !settings.value.frontCamera
        _torch.value = false
        dedup.clear()
        confirmer.clear()
        viewModelScope.launch { c.settings.setFrontCamera(front) }
    }

    fun toggleTorch() {
        _torch.value = !_torch.value
    }

    /** Called on the camera analysis thread for every decoded frame. */
    fun onDecoded(d: DecodedBarcode) {
        val raw = d.raw
        val format = d.format
        // Blank after the backend strip rule: the server would reject the op (422), so never enqueue it.
        if (BarcodeNormalizer.isBlank(raw)) return
        val symbology = symbologyFor(format)
        // Misread filter first: only reads confirmed by several identical frames reach dedupe/owner rule.
        if (!confirmer.onRead(d)) return
        if (!dedup.onDecoded(raw)) return

        revertRemoveIfIdle(clearDedup = false)
        val mode = _mode.value
        touch()
        val s = settings.value
        val code = BarcodeNormalizer.normalize(raw, symbology).code
        if (!guard.shouldCount(code, mode)) {
            feedback.alreadyCounted(s.sound, s.vibrate)
            _already.value = true
            alreadyJob?.cancel()
            alreadyJob = viewModelScope.launch {
                delay(ALREADY_COUNTED_MS)
                _already.value = false
            }
            return
        }
        feedback.signal(mode, s.sound, s.vibrate)

        viewModelScope.launch(Dispatchers.IO) {
            var preTrack: Long? = null
            val outcome = try {
                // Cache miss: the card is "looking up" before its history row can show up (no Register flash).
                c.scanRepository.recordScan(raw, symbology, mode, s.defaultLocationId) { opId -> preTrack = beginTrack(opId) }
            } catch (e: Exception) {
                preTrack?.let { t -> _track.update { if (it?.token == t) null else it } }
                guard.release(code, mode)
                throw e
            }
            guard.confirm(code, mode, outcome.clientOpId)
            currentOpId.value = outcome.clientOpId
            when {
                outcome.known -> {}
                // Cached server placeholder: already known to be unknown; still try to upgrade it.
                outcome.productId != null -> {
                    _snapshotRequests.tryEmit(outcome.clientOpId)
                    _unknownScans.tryEmit(outcome.clientOpId)
                    startLookup(outcome.clientOpId, raw, symbology, code, null)
                }
                // Cache miss: neutral "Looking up…" card until the answer arrives from any source.
                else -> {
                    _snapshotRequests.tryEmit(outcome.clientOpId)
                    startLookup(outcome.clientOpId, raw, symbology, code, preTrack)
                }
            }
            c.requestSync()
        }
    }

    /** Start the neutral "looking up" state for the card of [opId]; returns its token. */
    private fun beginTrack(opId: String): Long {
        val token = trackCounter.incrementAndGet()
        _track.value = LookupTrack(token, opId, SystemClock.elapsedRealtime())
        viewModelScope.launch {
            delay(CardLookup.SLOW_MS)
            _track.update { if (it?.token == token) it.copy(slow = true) else it }
        }
        return token
    }

    /** Live "watch the store by code" queries, at most [MAX_WATCHERS], one per code (newest wins). */
    private val watchers = LinkedHashMap<String, Job>()

    private fun registerWatcher(code: String, job: Job) {
        synchronized(watchers) {
            watchers.remove(code)?.cancel()
            watchers[code] = job
            while (watchers.size > MAX_WATCHERS) {
                val eldest = watchers.keys.first()
                watchers.remove(eldest)?.cancel()
            }
        }
        job.invokeOnCompletion { synchronized(watchers) { if (watchers[code] === job) watchers.remove(code) } }
    }

    /**
     * Resolve a barcode that is not (really) in the local cache: ask the server (retried), and independently watch
     * the local store by code so the sync OpResult / snapshot / changes pull also resolve the card. When the
     * lookup settles as unknown the live watcher is dropped (one cheap re-check later); [track] is the card's
     * lookup token (null = no card state, e.g. a cached placeholder being upgraded).
     */
    private fun startLookup(opId: String, raw: String, symbology: String, code: String, track: Long?) {
        viewModelScope.launch(Dispatchers.IO) {
            val watcher = launch {
                withTimeoutOrNull(CardLookup.TTL_MS) {
                    c.db.productDao().observeByCode(code).filterNotNull().first { p ->
                        c.scanRepository.linkScans(raw, p.id, p.name)
                        p.status != "unknown"
                    }
                }
            }
            registerWatcher(code, watcher)
            val outcome = try {
                c.barcodeLookup.lookup(raw, symbology)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (_: Exception) {
                LookupOutcome.FAILED
            }
            if (outcome == LookupOutcome.FOUND) watcher.cancel()
            if (outcome == LookupOutcome.UNKNOWN) {
                if (watcher.isActive) watcher.cancel()
                if (track != null) settleUnknown(opId, track)
                // Enrichment may finish later: one cheap re-check instead of a live query.
                delay(RECHECK_MS)
                c.db.productDao().observeByCode(code).first()?.let { c.scanRepository.linkScans(raw, it.id, it.name) }
            }
        }
    }

    private fun settleUnknown(opId: String, token: Long) {
        val track = _track.value
        if (track == null || track.token != token) return
        _track.value = track.copy(settledUnknown = true)
        if (CardLookup.shouldCueUnknown(currentOpId.value, track, SystemClock.elapsedRealtime())) {
            val s = settings.value
            feedback.unknown(s.sound, s.vibrate)
            _unknownScans.tryEmit(track.opId)
        }
    }

    /**
     * Register the product behind an unknown scan. The server creates the placeholder when the op
     * syncs, so a scan that has not synced yet is pushed now and given a few seconds to come back.
     */
    fun register(clientOpId: String) {
        viewModelScope.launch {
            c.requestSync()
            val productId = withTimeoutOrNull(REGISTER_WAIT_MS) {
                c.db.historyDao().observeProductId(clientOpId).filterNotNull().first()
            }
            if (productId != null) {
                _openForRegister.tryEmit(productId)
            } else {
                _events.tryEmit(UiMessage(R.string.register_later))
            }
        }
    }

    /** Keep the camera frame of an unknown scan; it becomes the product's photo once synced. */
    fun keepSnapshot(clientOpId: String, frame: android.graphics.Bitmap) {
        viewModelScope.launch {
            c.snapshots.keep(clientOpId, frame)
            c.requestSync()
        }
    }

    /** +1/+2/+5 on the last-scanned card: extra op for the same product/barcode with the card's own op type. */
    fun addExtra(row: HistoryRow, quantity: Int) {
        touch()
        val loc = settings.value.defaultLocationId
        viewModelScope.launch(Dispatchers.IO) {
            val extra = c.scanRepository.addExtra(
                row.entry.productId, row.entry.barcode, row.entry.symbology, row.entry.type, quantity.toDouble(), loc,
            ) { newOpId ->
                // The extra op becomes the last card: a running lookup now belongs to it (before the row exists).
                _track.update { if (it?.opId == row.entry.clientOpId) it.copy(opId = newOpId) else it }
            }
            if (extra != null) currentOpId.value = extra.clientOpId
            c.requestSync()
        }
    }

    fun undo() {
        viewModelScope.launch(Dispatchers.IO) {
            val outcome = c.scanRepository.undoLast()
            outcome.undoneClientOpId?.let(guard::onUndone)
            when (outcome.result) {
                UndoResult.NOTHING -> _events.tryEmit(UiMessage(R.string.snack_nothing_to_undo))
                UndoResult.REMOVED_PENDING -> _events.tryEmit(UiMessage(R.string.snack_undone))
                UndoResult.QUEUED -> {
                    _events.tryEmit(UiMessage(R.string.snack_undone))
                    c.requestSync()
                }
            }
        }
    }

    private fun touch() {
        lastActivityMs = SystemClock.elapsedRealtime()
    }

    private fun revertRemoveIfIdle(clearDedup: Boolean) {
        val current = _mode.value
        val resolved = ModePolicy.resolve(
            current, lastActivityMs, SystemClock.elapsedRealtime(), settings.value.serverRemoveTimeoutMin,
        )
        if (resolved != current) {
            applyMode(resolved, clearDedup)
            _events.tryEmit(UiMessage(R.string.snack_mode_reverted))
        }
    }

    private fun applyMode(mode: ScanMode, clearDedup: Boolean) {
        _mode.value = mode
        if (clearDedup) {
            dedup.clear()
            confirmer.clear()
        }
        guard.reset()
        viewModelScope.launch { c.settings.setMode(mode) }
    }

    override fun onCleared() {
        feedback.release()
    }
}
