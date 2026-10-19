package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QuantityMathTest {
    @Test
    fun signedDeltas() {
        assertEquals(2.0, QuantityMath.signedDelta("add", 2.0), 0.0)
        assertEquals(-2.0, QuantityMath.signedDelta("remove", 2.0), 0.0)
        assertEquals(-1.5, QuantityMath.signedDelta("adjust", -1.5), 0.0)
        assertEquals(0.0, QuantityMath.signedDelta("move", 3.0), 0.0)
        assertEquals(0.0, QuantityMath.signedDelta("undo", 3.0), 0.0)
    }

    @Test
    fun removalNeverGoesBelowZero() {
        assertEquals(-1.0, QuantityMath.clampedRemoveDelta(1.0, 5.0), 0.0)
        assertEquals(-0.5, QuantityMath.clampedRemoveDelta(1.0, 0.5), 0.0)
        assertEquals(0.0, QuantityMath.clampedRemoveDelta(1.0, 0.0), 0.0)
        assertEquals(0.0, QuantityMath.clampedRemoveDelta(1.0, -3.0), 0.0)
    }

    @Test
    fun displayIsServerTotalPlusPendingDeltas() {
        assertEquals(3.0, QuantityMath.displayQuantity(3.0, emptyList()), 0.0)
        assertEquals(4.0, QuantityMath.displayQuantity(3.0, listOf(1.0, 1.0, -1.0)), 0.0)
        // a scan add, then undo of a synced op (compensating negative delta)
        assertEquals(3.0, QuantityMath.displayQuantity(3.0, listOf(1.0, -1.0)), 0.0)
    }

    @Test
    fun lowStock() {
        assertTrue(QuantityMath.isLowStock(1.0, 2.0))
        assertFalse(QuantityMath.isLowStock(2.0, 2.0))
        assertFalse(QuantityMath.isLowStock(0.0, null))
    }

    @Test
    fun formatting() {
        assertEquals("3", QuantityMath.format(3.0))
        assertEquals("1,5", QuantityMath.format(1.5))
        assertEquals("0,25", QuantityMath.format(0.25))
        assertEquals("0", QuantityMath.format(0.0))
        assertEquals("0", QuantityMath.format(-0.0001))
        assertEquals("12,346", QuantityMath.format(12.3456))
    }

    @Test
    fun removeModeRevertsAfterIdleTimeout() {
        val min = 60_000L
        assertEquals(ScanMode.REMOVE, ModePolicy.resolve(ScanMode.REMOVE, 0, 9 * min, 10))
        assertEquals(ScanMode.ADD, ModePolicy.resolve(ScanMode.REMOVE, 0, 10 * min, 10))
        assertEquals(ScanMode.ADD, ModePolicy.resolve(ScanMode.ADD, 0, 99 * min, 10))
        assertEquals(ScanMode.REMOVE, ModePolicy.resolve(ScanMode.REMOVE, 0, 99 * min, 0)) // 0 = never
    }

    @Test
    fun modeKeys() {
        assertEquals(ScanMode.REMOVE, ScanMode.fromKey("remove"))
        assertEquals(ScanMode.ADD, ScanMode.fromKey("add"))
        assertEquals(ScanMode.ADD, ScanMode.fromKey(null))
        assertEquals("remove", ScanMode.REMOVE.apiType)
    }
}
