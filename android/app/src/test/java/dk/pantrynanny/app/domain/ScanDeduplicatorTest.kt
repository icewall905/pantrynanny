package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ScanDeduplicatorTest {
    private var now = 0L
    private fun dedup(rearm: Long = 600) = ScanDeduplicator(rearm) { now }

    @Test
    fun firstSightingFires() {
        assertTrue(dedup().onDecoded("A"))
    }

    @Test
    fun heldBarcodeNeverRefires() {
        val d = dedup()
        assertTrue(d.onDecoded("A"))
        // decoded continuously every 33 ms for 5 seconds
        repeat(150) {
            now += 33
            assertFalse("frame $it", d.onDecoded("A"))
        }
    }

    @Test
    fun reentryAfterRearmFires() {
        val d = dedup()
        assertTrue(d.onDecoded("A"))
        now += 600 // absent for exactly REARM_MS (>=)
        assertTrue(d.onDecoded("A"))
        assertFalse(d.onDecoded("A"))
    }

    @Test
    fun gapShorterThanRearmDoesNotFire() {
        val d = dedup()
        assertTrue(d.onDecoded("A"))
        now += 599
        assertFalse(d.onDecoded("A"))
        // the miss window restarts from the last sighting
        now += 599
        assertFalse(d.onDecoded("A"))
    }

    @Test
    fun differentCodesAreIndependent() {
        val d = dedup()
        assertTrue(d.onDecoded("A"))
        now += 10
        assertTrue(d.onDecoded("B"))
        now += 10
        assertFalse(d.onDecoded("A"))
        assertFalse(d.onDecoded("B"))
    }

    @Test
    fun clearOnModeSwitchForgetsEverything() {
        val d = dedup()
        assertTrue(d.onDecoded("A"))
        d.clear()
        assertEquals(0, d.trackedCount())
        assertTrue(d.onDecoded("A"))
    }

    @Test
    fun oldEntriesAreGarbageCollected() {
        val d = dedup()
        d.onDecoded("A")
        d.onDecoded("B")
        assertEquals(2, d.trackedCount())
        now += ScanDeduplicator.GC_MS + 1
        d.onDecoded("C")
        assertEquals(1, d.trackedCount())
    }

    @Test
    fun rearmIsClamped() {
        assertEquals(250L, dedup(10).rearmMs)
        assertEquals(3000L, dedup(99_999).rearmMs)
        val d = dedup()
        d.rearmMs = 1000
        assertEquals(1000L, d.rearmMs)
        d.rearmMs = 1
        assertEquals(250L, d.rearmMs)
    }

    @Test
    fun customRearmIsHonoured() {
        val d = dedup(1500)
        assertTrue(d.onDecoded("A"))
        now += 1499
        assertFalse(d.onDecoded("A"))
        now += 1500
        assertTrue(d.onDecoded("A"))
    }

    @Test
    fun checksumInvalidNeedsTwoFramesWithin250ms() {
        val d = dedup()
        assertFalse(d.onDecoded("X", checksumValid = false))
        now += 100
        assertTrue(d.onDecoded("X", checksumValid = false))
        now += 50
        assertFalse(d.onDecoded("X", checksumValid = false)) // held: no refire
    }

    @Test
    fun checksumInvalidSingleReadIsDiscarded() {
        val d = dedup()
        assertFalse(d.onDecoded("X", checksumValid = false))
        now += 400 // second read too late: counts as a new first read
        assertFalse(d.onDecoded("X", checksumValid = false))
        now += 100
        assertTrue(d.onDecoded("X", checksumValid = false))
    }

    @Test
    fun checksumValidFiresImmediately() {
        assertTrue(dedup().onDecoded("4006381333931", checksumValid = true))
    }
}
