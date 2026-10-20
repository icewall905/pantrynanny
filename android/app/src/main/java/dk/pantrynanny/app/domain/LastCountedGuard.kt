package dk.pantrynanny.app.domain

/**
 * "Never count the same item twice in succession": a fired scan whose normalised code equals the
 * immediately previous COUNTED scan in the same mode is not counted; the user taps +1/+2/+5 instead.
 *
 * Resets (the next scan of the same code counts again): different code in between, [reset] on a mode
 * switch or an undo, and returning from the background after more than [SESSION_MS].
 * Thread-safe (camera thread + UI thread).
 */
class LastCountedGuard(private val clock: () -> Long) {
    private var lastCode: String? = null
    private var lastMode: ScanMode? = null
    private var lastOpId: String? = null
    private var backgroundedAt: Long? = null

    /**
     * True when the scan should be counted. The scan is claimed immediately (so a quick second fire
     * cannot slip through before the write finishes); call [confirm] once the op is durably stored,
     * or [release] if the write failed.
     */
    @Synchronized
    fun shouldCount(code: String, mode: ScanMode): Boolean {
        if (code == lastCode && mode == lastMode) return false
        lastCode = code
        lastMode = mode
        lastOpId = null
        return true
    }

    /** The claimed scan was stored as op [clientOpId]. */
    @Synchronized
    fun confirm(code: String, mode: ScanMode, clientOpId: String) {
        if (code == lastCode && mode == lastMode) lastOpId = clientOpId
    }

    /** The claimed scan was not stored (write failed): forget the claim. */
    @Synchronized
    fun release(code: String, mode: ScanMode) {
        if (code == lastCode && mode == lastMode && lastOpId == null) reset()
    }

    /** An op was undone; only undoing the last counted scan op re-arms its code. */
    @Synchronized
    fun onUndone(clientOpId: String) {
        if (clientOpId == lastOpId) reset()
    }

    /** The normalised code and mode of the last counted scan (null when none / reset). */
    @Synchronized
    fun lastCode(): String? = lastCode

    @Synchronized
    fun reset() {
        lastCode = null
        lastMode = null
        lastOpId = null
    }

    @Synchronized
    fun onBackgrounded() {
        backgroundedAt = clock()
    }

    @Synchronized
    fun onForegrounded() {
        val at = backgroundedAt ?: return
        backgroundedAt = null
        if (clock() - at > SESSION_MS) reset()
    }

    companion object {
        const val SESSION_MS = 10 * 60_000L
    }
}
