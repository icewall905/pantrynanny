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
    private var backgroundedAt: Long? = null

    /** True when the scan should be counted (and is recorded as the last counted one). */
    @Synchronized
    fun shouldCount(code: String, mode: ScanMode): Boolean {
        if (code == lastCode && mode == lastMode) return false
        lastCode = code
        lastMode = mode
        return true
    }

    @Synchronized
    fun reset() {
        lastCode = null
        lastMode = null
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
