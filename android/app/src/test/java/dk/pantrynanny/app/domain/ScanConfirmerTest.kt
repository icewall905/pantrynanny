package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ScanConfirmerTest {
    private var now = 0L
    private fun confirmer() = ScanConfirmer { now }
    private val centre = NormBox(0.3f, 0.4f, 0.7f, 0.6f)
    private fun read(code: String, box: NormBox? = centre, weak: Boolean = false) = DecodedBarcode(code, 0, box, weak)

    @Test
    fun singleReadNeverFires() {
        assertFalse(confirmer().onRead(read("A")))
    }

    @Test
    fun twoIdenticalReadsInWindowFire() {
        val c = confirmer()
        assertFalse(c.onRead(read("A")))
        now += 40
        assertTrue(c.onRead(read("A")))
    }

    @Test
    fun heldCodeKeepsPassingConfirmedReads() {
        val c = confirmer()
        c.onRead(read("A"))
        repeat(20) {
            now += 33
            assertTrue(c.onRead(read("A")))
        }
    }

    @Test
    fun readsSpreadBeyondWindowDoNotCombine() {
        val c = confirmer()
        assertFalse(c.onRead(read("A")))
        now += 700
        assertFalse(c.onRead(read("A")))
        now += 700
        assertFalse(c.onRead(read("A")))
    }

    @Test
    fun alternatingMisreadsFireOnlyWhenTrueCodeHasClearMajority() {
        val c = confirmer()
        assertFalse(c.onRead(read("A1"))); now += 40
        assertFalse(c.onRead(read("A"))); now += 40
        assertFalse(c.onRead(read("A2"))); now += 40
        assertTrue(c.onRead(read("A")))
    }

    @Test
    fun competingCodeWithAsManyReadsBlocksUntilClearWinner() {
        val c = confirmer()
        assertFalse(c.onRead(read("A1"))); now += 40
        assertTrue(c.onRead(read("A1"))); now += 40
        assertFalse(c.onRead(read("A"))); now += 40
        assertFalse(c.onRead(read("A"))) // 2 vs 2: no clear winner
        now += 40
        assertTrue(c.onRead(read("A"))) // 3 vs 2
    }

    @Test
    fun competingCodeFromOtherRegionDoesNotBlock() {
        val c = confirmer()
        val other = NormBox(0.0f, 0.0f, 0.2f, 0.2f)
        c.onRead(read("B", other)); now += 10
        c.onRead(read("B", other)); now += 10
        c.onRead(read("A")); now += 10
        // A has 2 reads vs B 2 reads but B is elsewhere
        assertTrue(c.onRead(read("A")))
    }

    @Test
    fun weakFirstSightingNeedsThreeReads() {
        val c = confirmer()
        assertFalse(c.onRead(read("A", weak = true))); now += 40
        assertFalse(c.onRead(read("A"))); now += 40
        assertTrue(c.onRead(read("A")))
    }

    @Test
    fun clearForgetsReads() {
        val c = confirmer()
        c.onRead(read("A"))
        c.clear()
        now += 10
        assertFalse(c.onRead(read("A")))
    }
}

class FrameSelectorTest {
    private fun cand(name: String, l: Int, t: Int, r: Int, b: Int) = FrameCandidate(name, l, t, r, b)

    @Test
    fun uprightSizeSwapsForQuarterTurns() {
        assertEquals(1280 to 720, FrameSelector.uprightSize(1280, 720, 0))
        assertEquals(1280 to 720, FrameSelector.uprightSize(1280, 720, 180))
        assertEquals(720 to 1280, FrameSelector.uprightSize(1280, 720, 90))
        assertEquals(720 to 1280, FrameSelector.uprightSize(1280, 720, 270))
    }

    @Test
    fun edgeTouchingBoxIgnored() {
        val r = FrameSelector.select(listOf(cand("edge", 0, 300, 400, 400)), 720, 1280)
        assertNull(r)
    }

    @Test
    fun picksMostCentralNonEdgeBox() {
        val r = FrameSelector.select(
            listOf(cand("far", 50, 100, 250, 200), cand("mid", 260, 560, 460, 700), cand("edge", 0, 600, 300, 700)),
            720, 1280,
        )!!
        assertEquals("mid", r.first)
    }

    @Test
    fun smallBoxIsWeakLargeCentralIsNot() {
        val small = FrameSelector.select(listOf(cand("s", 300, 600, 400, 640)), 720, 1280)!!
        assertTrue(small.third)
        val big = FrameSelector.select(listOf(cand("b", 100, 500, 620, 780)), 720, 1280)!!
        assertFalse(big.third)
    }
}
