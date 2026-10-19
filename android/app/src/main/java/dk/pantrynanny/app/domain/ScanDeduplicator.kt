package dk.pantrynanny.app.domain

/**
 * Scanner duplicate-suppression exactly as specified in docs/api-contract.md section 4.
 *
 * - Per decoded value we keep `lastSeenAt`. A value fires when it is unknown or has been absent
 *   (not decoded) for at least [rearmMs]. Every decode refreshes `lastSeenAt`, fired or not, so a
 *   barcode held in view never re-fires.
 * - Different codes are independent (no global cooldown).
 * - Optional confirmation filter: a code whose checksum is NOT valid must be decoded twice
 *   within [CONFIRM_WINDOW_MS] before it fires. Checksum-valid codes fire immediately.
 * - [clear] (called on Add/Remove mode switch) forgets everything.
 * - Entries older than [GC_MS] are garbage collected.
 *
 * Thread-safe (called from the camera analysis thread and the UI thread).
 */
class ScanDeduplicator(rearmMs: Long = DEFAULT_REARM_MS, private val clock: () -> Long) {

    @Volatile
    var rearmMs: Long = rearmMs.coerceIn(MIN_REARM_MS, MAX_REARM_MS)
        set(value) {
            field = value.coerceIn(MIN_REARM_MS, MAX_REARM_MS)
        }

    private val tracked = HashMap<String, Long>()
    private val candidates = HashMap<String, Long>()

    /** Returns true when this decode should be counted as a new item. */
    @Synchronized
    fun onDecoded(code: String, checksumValid: Boolean = true): Boolean {
        val t = clock()
        gc(t)
        val last = tracked[code]
        val absentLongEnough = last == null || (t - last) >= rearmMs
        if (!absentLongEnough) {
            tracked[code] = t
            candidates.remove(code)
            return false
        }
        if (!checksumValid) {
            val first = candidates[code]
            if (first == null || (t - first) > CONFIRM_WINDOW_MS) {
                candidates[code] = t
                return false
            }
        }
        candidates.remove(code)
        tracked[code] = t
        return true
    }

    @Synchronized
    fun clear() {
        tracked.clear()
        candidates.clear()
    }

    @Synchronized
    fun trackedCount(): Int = tracked.size

    private fun gc(now: Long) {
        if (tracked.isNotEmpty()) tracked.entries.removeAll { now - it.value > GC_MS }
        if (candidates.isNotEmpty()) candidates.entries.removeAll { now - it.value > GC_MS }
    }

    companion object {
        const val DEFAULT_REARM_MS = 600L
        const val MIN_REARM_MS = 250L
        const val MAX_REARM_MS = 3000L
        const val CONFIRM_WINDOW_MS = 250L
        const val GC_MS = 10_000L
    }
}
