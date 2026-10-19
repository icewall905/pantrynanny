package dk.pantrynanny.app.domain

import java.math.BigDecimal
import java.math.RoundingMode

enum class ScanMode(val apiType: String) {
    ADD("add"),
    REMOVE("remove");

    companion object {
        fun fromKey(key: String?): ScanMode = if (key == "remove") REMOVE else ADD
    }
}

object ModePolicy {
    /** Remove mode reverts to Add after [timeoutMin] idle minutes. timeoutMin <= 0 disables the timeout. */
    fun resolve(mode: ScanMode, lastActivityMs: Long, nowMs: Long, timeoutMin: Int): ScanMode =
        if (mode == ScanMode.REMOVE && timeoutMin > 0 && nowMs - lastActivityMs >= timeoutMin * 60_000L) {
            ScanMode.ADD
        } else {
            mode
        }
}

/** Pure op-queue / quantity arithmetic. Server total is authoritative; pending deltas are added on top. */
object QuantityMath {
    const val EPSILON = 0.0005

    /** Signed stock delta of an op of [type] with positive [quantity] ("adjust" is already signed). */
    fun signedDelta(type: String, quantity: Double): Double = when (type) {
        "add" -> quantity
        "remove" -> -quantity
        "adjust" -> quantity
        else -> 0.0
    }

    /**
     * Optimistic local delta of a removal: never takes the displayed stock below zero
     * (the server clamps as well when negative stock is not allowed).
     */
    fun clampedRemoveDelta(requested: Double, available: Double): Double =
        -minOf(requested, maxOf(available, 0.0))

    fun displayQuantity(serverTotal: Double, pendingDeltas: Iterable<Double>): Double =
        serverTotal + pendingDeltas.sum()

    fun isLowStock(display: Double, minStock: Double?): Boolean =
        minStock != null && display < minStock - EPSILON

    /** "3", "1,5", "0,25" - Danish decimal comma, at most 3 decimals. */
    fun format(q: Double): String {
        val v = if (kotlin.math.abs(q) < EPSILON) 0.0 else q
        val s = BigDecimal.valueOf(v).setScale(3, RoundingMode.HALF_UP).stripTrailingZeros().toPlainString()
        return s.replace('.', ',')
    }
}

enum class UndoAction { DELETE_LOCAL_OP, ENQUEUE_UNDO_OP }

/**
 * Decides how to undo a scan so uploads stay exactly-once. An op may only be deleted locally if
 * it was NEVER handed to the uploader (`attempts == 0`, status pending) or was rejected by the
 * server. Anything that may have reached the server (inflight, or pending again after a failed
 * upload, i.e. attempts > 0, or already synced and removed) keeps the original and gets a
 * compensating `undo` op queued after it.
 */
object UndoPlanner {
    fun decide(opStatus: String?, attempts: Int): UndoAction = when {
        opStatus == "rejected" -> UndoAction.DELETE_LOCAL_OP
        opStatus == "pending" && attempts == 0 -> UndoAction.DELETE_LOCAL_OP
        else -> UndoAction.ENQUEUE_UNDO_OP
    }
}
