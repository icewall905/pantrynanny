package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.LocalDate

class PlacementTest {
    private val today = LocalDate.of(2026, 1, 31)

    @Test
    fun expiryDates() {
        assertEquals(LocalDate.of(2026, 2, 3), Placement.expiryDate(ExpiryChip.Days(3), today))
        assertEquals(LocalDate.of(2026, 2, 7), Placement.expiryDate(ExpiryChip.Weeks(1), today))
        // Month math clamps to the end of a shorter month.
        assertEquals(LocalDate.of(2026, 2, 28), Placement.expiryDate(ExpiryChip.Months(1), today))
        assertEquals(LocalDate.of(2026, 7, 31), Placement.expiryDate(ExpiryChip.Months(6), today))
        assertNull(Placement.expiryDate(ExpiryChip.None, today))
    }

    @Test
    fun categoryChipMatchesPresetsByExactDays() {
        assertNull(Placement.categoryChip(null))
        assertEquals(ExpiryChip.Days(3), Placement.categoryChip(3))
        assertEquals(ExpiryChip.Weeks(1), Placement.categoryChip(7))
        // 30 days is not "+1 m": an extra exact chip instead.
        assertEquals(ExpiryChip.Days(30), Placement.categoryChip(30))
        assertNull(Placement.categoryChip(-1))
    }

    @Test
    fun chipsAddCategoryChipOnlyWhenNotAPreset() {
        assertEquals(Placement.PRESETS, Placement.chips(null))
        assertEquals(Placement.PRESETS, Placement.chips(7))
        assertEquals(listOf<ExpiryChip>(ExpiryChip.Days(10)) + Placement.PRESETS, Placement.chips(10))
    }

    @Test
    fun currentLocationFollowsServerOrder() {
        val locs = listOf(PlaceLocation("a", false, 0), PlaceLocation("b", true, 5), PlaceLocation("c", false, 1))
        assertEquals("c", Placement.currentLocation("c", "a", "b", locs))
        assertEquals("a", Placement.currentLocation(null, "a", "c", locs))
        assertEquals("c", Placement.currentLocation(null, "gone", "c", locs))
        assertEquals("b", Placement.currentLocation(null, null, null, locs))
        assertEquals("a", Placement.currentLocation(null, null, null, locs.map { it.copy(isDefault = false) }))
        assertNull(Placement.currentLocation("x", null, null, emptyList()))
    }
}
