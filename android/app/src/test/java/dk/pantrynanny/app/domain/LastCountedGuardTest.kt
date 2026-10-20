package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LastCountedGuardTest {
    private var now = 0L
    private val guard = LastCountedGuard { now }

    /** Tiny in-memory ledger standing in for the repository: one entry per enqueued op. */
    private val ops = ArrayList<Pair<String, Double>>()
    private var lastScanOp = ""
    private fun qty(code: String) = ops.filter { it.first == code }.sumOf { it.second }

    private fun scan(code: String, mode: ScanMode = ScanMode.ADD): Boolean {
        val counted = guard.shouldCount(code, mode)
        if (counted) {
            ops += code to 1.0
            guard.confirm(code, mode, "op${ops.size}-$code")
            lastScanOp = "op${ops.size}-$code"
        }
        return counted
    }

    @Test
    fun sameCodeTwiceWithLongGapCountsOnce() {
        assertTrue(scan("A"))
        now += 60_000
        assertFalse(scan("A"))
        assertEquals(1, ops.size)
    }

    @Test
    fun abaCountsThree() {
        scan("A"); scan("B"); scan("A")
        assertEquals(3, ops.size)
    }

    @Test
    fun modeSwitchCountsInBothModes() {
        assertTrue(scan("A", ScanMode.ADD))
        guard.reset()
        assertTrue(scan("A", ScanMode.REMOVE))
        assertEquals(2, ops.size)
    }

    @Test
    fun differentModeCountsEvenWithoutReset() {
        scan("A", ScanMode.ADD)
        assertTrue(scan("A", ScanMode.REMOVE))
    }

    @Test
    fun undoThenSameCodeCountsAgain() {
        scan("A")
        ops.removeAt(ops.lastIndex); guard.onUndone(lastScanOp)
        assertTrue(scan("A"))
        assertEquals(1, ops.size)
    }

    @Test
    fun extraButtonAfterScanAddsQuantityWithTwoOps() {
        scan("A")
        assertFalse(scan("A"))
        ops += "A" to 2.0 // +2 button: its own op
        assertEquals(3.0, qty("A"), 0.0)
        assertEquals(2, ops.size)
    }

    @Test
    fun longBackgroundStartsNewSession() {
        scan("A")
        guard.onBackgrounded(); now += LastCountedGuard.SESSION_MS + 1; guard.onForegrounded()
        assertTrue(scan("A"))
    }

    @Test
    fun shortBackgroundKeepsGuard() {
        scan("A")
        guard.onBackgrounded(); now += 60_000; guard.onForegrounded()
        assertFalse(scan("A"))
    }

    @Test
    fun undoingExtraOpDoesNotRearm() {
        scan("A")
        ops += "A" to 2.0
        guard.onUndone("extra-op") // not the scan op
        ops.removeAt(ops.lastIndex)
        assertFalse(scan("A"))
        assertEquals(1, ops.size)
    }

    @Test
    fun failedWriteReleasesClaim() {
        assertTrue(guard.shouldCount("A", ScanMode.ADD))
        guard.release("A", ScanMode.ADD)
        assertTrue(guard.shouldCount("A", ScanMode.ADD))
    }

    @Test
    fun migrationSqlAddsNullableColumn() {
        assertEquals(
            "ALTER TABLE scan_history ADD COLUMN symbology TEXT",
            dk.pantrynanny.app.data.local.Migrations.ADD_HISTORY_SYMBOLOGY,
        )
    }
}
