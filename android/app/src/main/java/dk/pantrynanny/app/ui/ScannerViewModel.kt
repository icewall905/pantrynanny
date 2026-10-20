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
import dk.pantrynanny.app.domain.ModePolicy
import dk.pantrynanny.app.domain.ScanDeduplicator
import dk.pantrynanny.app.domain.ScanMode
import kotlinx.coroutines.Dispatchers
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
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/** How long "Registrer" waits for an unsynced unknown scan to come back with its placeholder product. */
private const val REGISTER_WAIT_MS = 10_000L

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
)

class ScannerViewModel(private val c: AppContainer) : ViewModel() {

    private val settings: StateFlow<AppSettings> =
        c.settings.flow.stateIn(viewModelScope, SharingStarted.Eagerly, AppSettings())

    private val _mode = MutableStateFlow(ScanMode.ADD)
    private val _torch = MutableStateFlow(false)

    private val dedup = ScanDeduplicator(ScanDeduplicator.DEFAULT_REARM_MS) { SystemClock.elapsedRealtime() }
    private val feedback = Feedback(c.app)

    @Volatile
    private var lastActivityMs = SystemClock.elapsedRealtime()

    private val _events = MutableSharedFlow<UiMessage>(extraBufferCapacity = 16)
    val events: SharedFlow<UiMessage> = _events.asSharedFlow()

    /** client_op_id of a scan whose barcode is not a known product yet (offer "Registrer"). */
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
        viewModelScope.launch { c.settings.setFrontCamera(front) }
    }

    fun toggleTorch() {
        _torch.value = !_torch.value
    }

    /** Called on the camera analysis thread for every decoded frame. */
    fun onDecoded(raw: String, format: Int) {
        // Blank after the backend strip rule: the server would reject the op (422), so never enqueue it.
        if (BarcodeNormalizer.isBlank(raw)) return
        val symbology = symbologyFor(format)
        val checksumValid = BarcodeNormalizer.normalize(raw, symbology).valid
        if (!dedup.onDecoded(raw, checksumValid)) return

        revertRemoveIfIdle(clearDedup = false)
        val mode = _mode.value
        touch()
        val s = settings.value
        feedback.signal(mode, s.sound, s.vibrate)

        viewModelScope.launch(Dispatchers.IO) {
            val outcome = c.scanRepository.recordScan(raw, symbology, mode, s.defaultLocationId)
            if (!outcome.known) _unknownScans.tryEmit(outcome.clientOpId)
            c.requestSync()
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

    fun undo() {
        viewModelScope.launch(Dispatchers.IO) {
            when (c.scanRepository.undoLast()) {
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
        if (clearDedup) dedup.clear()
        viewModelScope.launch { c.settings.setMode(mode) }
    }

    override fun onCleared() {
        feedback.release()
    }
}
