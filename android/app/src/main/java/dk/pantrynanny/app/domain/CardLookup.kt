package dk.pantrynanny.app.domain

/** What the last-scanned card shows for its product. */
enum class CardPhase { KNOWN, LOOKING, SLOW, UNKNOWN }

/** The in-flight background lookup behind the last-scanned card (a local cache miss). */
data class LookupTrack(
    val token: Long,
    val opId: String,
    val startedAtMs: Long,
    /** The lookup answered not_found / created_placeholder. */
    val settledUnknown: Boolean = false,
    /** No answer after [CardLookup.SLOW_MS]. */
    val slow: Boolean = false,
)

object CardLookup {
    const val SLOW_MS = 10_000L
    const val CUE_MAX_AGE_MS = 5_000L
    const val TTL_MS = 120_000L
    val RETRY_DELAYS_MS = longArrayOf(500, 2000)

    /**
     * [prodStatus] is the joined product status of the card's history row (null = no product linked yet). A real
     * product always wins; otherwise a card under an active [track] stays neutral until the lookup settles.
     */
    fun phase(opId: String, prodStatus: String?, track: LookupTrack?): CardPhase = when {
        prodStatus != null && prodStatus != "unknown" -> CardPhase.KNOWN
        track == null || track.opId != opId -> CardPhase.UNKNOWN
        track.settledUnknown -> CardPhase.UNKNOWN
        track.slow -> CardPhase.SLOW
        else -> CardPhase.LOOKING
    }

    /** Unknown cue only if that card is still the current one and fresh. */
    fun shouldCueUnknown(currentOpId: String?, track: LookupTrack, nowMs: Long): Boolean =
        currentOpId == track.opId && nowMs - track.startedAtMs < CUE_MAX_AGE_MS
}
