package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CardLookupTest {
    private val track = LookupTrack(1, "op1", startedAtMs = 1000)

    @Test
    fun cacheMissStartsNeutral() {
        assertEquals(CardPhase.LOOKING, CardLookup.phase("op1", null, track))
    }

    @Test
    fun slowAfterTimeoutKeepsListening() {
        assertEquals(CardPhase.SLOW, CardLookup.phase("op1", null, track.copy(slow = true)))
    }

    @Test
    fun settledUnknownShowsUnknown() {
        assertEquals(CardPhase.UNKNOWN, CardLookup.phase("op1", null, track.copy(settledUnknown = true)))
    }

    @Test
    fun anySourceProductWinsAndPlaceholderStaysPending() {
        assertEquals(CardPhase.KNOWN, CardLookup.phase("op1", "known", track))
        assertEquals(CardPhase.KNOWN, CardLookup.phase("op1", "known", track.copy(settledUnknown = true)))
        assertEquals(CardPhase.LOOKING, CardLookup.phase("op1", "unknown", track))
    }

    @Test
    fun untrackedCardKeepsLegacyBehaviour() {
        assertEquals(CardPhase.UNKNOWN, CardLookup.phase("op2", null, track))
        assertEquals(CardPhase.KNOWN, CardLookup.phase("op2", "known", null))
    }

    @Test
    fun unknownCueOnlyForCurrentFreshCard() {
        assertTrue(CardLookup.shouldCueUnknown("op1", track, 1000 + 4_999))
        assertFalse(CardLookup.shouldCueUnknown("op1", track, 1000 + 5_000))
        assertFalse(CardLookup.shouldCueUnknown("op2", track, 1500))
        assertFalse(CardLookup.shouldCueUnknown(null, track, 1500))
    }
}
