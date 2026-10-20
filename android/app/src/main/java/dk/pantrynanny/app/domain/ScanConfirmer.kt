package dk.pantrynanny.app.domain

/** A bounding box as fractions (0..1) of the upright frame. */
data class NormBox(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    val width: Float get() = right - left
    val height: Float get() = bottom - top
    val area: Float get() = width * height
    val centerX: Float get() = (left + right) / 2f
    val centerY: Float get() = (top + bottom) / 2f

    fun overlaps(o: NormBox): Boolean = left < o.right && o.left < right && top < o.bottom && o.top < bottom
}

/** One barcode picked from a camera frame. [weak]: small or near the frame edge, so it needs more confirming reads. */
data class DecodedBarcode(val raw: String, val format: Int, val box: NormBox? = null, val weak: Boolean = false)

/** An unfiltered barcode candidate in a frame (pixel box in the upright image). */
data class FrameCandidate<T>(val item: T, val left: Int, val top: Int, val right: Int, val bottom: Int)

/**
 * Picks the one barcode to consider per frame: boxes touching the frame edge are likely partial reads and are
 * ignored; of the rest the one closest to the frame centre wins (ties: larger).
 */
object FrameSelector {
    /** Size of the image as ML Kit reports boxes for it: the (rotated) upright frame. */
    fun uprightSize(width: Int, height: Int, rotationDegrees: Int): Pair<Int, Int> =
        if (rotationDegrees % 180 == 0) width to height else height to width

    const val EDGE_TOUCH_FRACTION = 0.01f
    const val WEAK_EDGE_FRACTION = 0.04f
    const val WEAK_AREA_FRACTION = 0.02f

    fun toNorm(c: FrameCandidate<*>, w: Int, h: Int) =
        NormBox(c.left.toFloat() / w, c.top.toFloat() / h, c.right.toFloat() / w, c.bottom.toFloat() / h)

    fun touchesEdge(b: NormBox): Boolean =
        b.left <= EDGE_TOUCH_FRACTION || b.top <= EDGE_TOUCH_FRACTION ||
            b.right >= 1f - EDGE_TOUCH_FRACTION || b.bottom >= 1f - EDGE_TOUCH_FRACTION

    fun isWeak(b: NormBox): Boolean =
        b.area < WEAK_AREA_FRACTION ||
            b.left <= WEAK_EDGE_FRACTION || b.top <= WEAK_EDGE_FRACTION ||
            b.right >= 1f - WEAK_EDGE_FRACTION || b.bottom >= 1f - WEAK_EDGE_FRACTION

    /** Returns the chosen candidate with its normalised box and weak flag, or null when none qualifies. */
    fun <T> select(cands: List<FrameCandidate<T>>, w: Int, h: Int): Triple<T, NormBox, Boolean>? {
        if (w <= 0 || h <= 0) return null
        return cands.map { it to toNorm(it, w, h) }
            .filter { (_, b) -> b.width > 0f && b.height > 0f && !touchesEdge(b) }
            .minWithOrNull(
                compareBy<Pair<FrameCandidate<T>, NormBox>> { (_, b) ->
                    val dx = b.centerX - 0.5f
                    val dy = b.centerY - 0.5f
                    dx * dx + dy * dy
                }.thenByDescending { (_, b) -> b.area }
            )
            ?.let { (c, b) -> Triple(c.item, b, isWeak(b)) }
    }
}

/**
 * Misread filter in front of [ScanDeduplicator]: partial left-half decodes are often checksum-valid but wrong, and
 * differ from frame to frame, while the true code repeats. A read is passed on only when its raw value was decoded
 * by >= [minReads] frames within [windowMs] (>= [minReadsWeak] when the first sighting in the window was weak) and
 * no competing code from an overlapping region has as many reads. Passing on every confirmed read (not just the
 * first) keeps frame-dedupe semantics: a held barcode keeps refreshing the deduplicator.
 *
 * Thread-safe.
 */
class ScanConfirmer(
    private val windowMs: Long = DEFAULT_WINDOW_MS,
    private val minReads: Int = MIN_READS,
    private val minReadsWeak: Int = MIN_READS_WEAK,
    private val regionHoldMs: Long = REGION_HOLD_MS,
    private val clock: () -> Long,
) {
    private class Read(val code: String, val t: Long, val box: NormBox?, val weak: Boolean)

    private val reads = ArrayList<Read>()

    // Last confirmed code T: its region, last confirmed time and the reads it had in the window then.
    private var lastCode: String? = null
    private var lastRegion: NormBox? = null
    private var lastAt = 0L
    private var lastReads = 0

    /** True when [d] is now a confirmed read. */
    @Synchronized
    fun onRead(d: DecodedBarcode): Boolean {
        val t = clock()
        reads.removeAll { t - it.t > windowMs }
        reads.add(Read(d.raw, t, d.box, d.weak))

        val mine = reads.filter { it.code == d.raw }
        val need = if (mine.first().weak) minReadsWeak else minReads
        if (mine.size < need) return false
        // After T was confirmed, a different code from T's region (e.g. a late partial misread) is ignored for
        // [regionHoldMs] unless it has strictly more reads than T had.
        val tCode = lastCode
        if (tCode != null && tCode != d.raw && t - lastAt <= regionHoldMs) {
            val region = lastRegion
            val overlaps = region == null || d.box == null || region.overlaps(d.box)
            // Cap the bar: a held T has ~every frame in the window, which a legitimately different
            // product in the same spot could never beat. One read more than a fresh confirmation suffices
            // to outvote a misread repeated in 2–3 frames.
            if (overlaps && mine.size <= minOf(lastReads, minReads + 1)) return false
        }
        // Competitors: other codes read from a region overlapping this code's (unknown box = assume overlap),
        // The last CONFIRMED code's reads from before this code's first sighting don't count (that product was
        // swapped out); every other code — e.g. a real product not yet confirmed — keeps its full window.
        val regions = mine.mapNotNull { it.box }
        val since = mine.first().t
        val rivalBest = reads.filter { it.code != d.raw && !(it.code == lastCode && it.t < since) }
            .filter { r -> r.box == null || regions.isEmpty() || regions.any { it.overlaps(r.box) } }
            .groupBy { it.code }
            .maxOfOrNull { it.value.size } ?: 0
        if (mine.size <= rivalBest) return false
        lastCode = d.raw
        lastRegion = mine.mapNotNull { it.box }.lastOrNull()
        lastAt = t
        lastReads = mine.size
        return true
    }

    @Synchronized
    fun clear() {
        reads.clear()
        lastCode = null
    }

    companion object {
        const val DEFAULT_WINDOW_MS = 600L
        const val MIN_READS = 2
        const val MIN_READS_WEAK = 3
        const val REGION_HOLD_MS = 1000L
    }
}
