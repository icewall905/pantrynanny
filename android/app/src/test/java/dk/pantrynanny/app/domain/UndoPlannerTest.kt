package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Test

class UndoPlannerTest {
    @Test
    fun neverSentPendingOpIsDeleted() {
        assertEquals(UndoAction.DELETE_LOCAL_OP, UndoPlanner.decide("pending", 0))
    }

    @Test
    fun undoAfterFailedUploadKeepsOriginalAndQueuesUndo() {
        // upload attempted (attempts=1) then reverted to pending after a network error / 5xx:
        // the server may have applied it, so deleting would break exactly-once.
        assertEquals(UndoAction.ENQUEUE_UNDO_OP, UndoPlanner.decide("pending", 1))
        assertEquals(UndoAction.ENQUEUE_UNDO_OP, UndoPlanner.decide("pending", 5))
    }

    @Test
    fun inflightOrAlreadySyncedOpGetsCompensatingUndo() {
        assertEquals(UndoAction.ENQUEUE_UNDO_OP, UndoPlanner.decide("inflight", 1))
        assertEquals(UndoAction.ENQUEUE_UNDO_OP, UndoPlanner.decide(null, 0)) // already applied and removed
    }

    @Test
    fun rejectedOpIsSimplyDropped() {
        assertEquals(UndoAction.DELETE_LOCAL_OP, UndoPlanner.decide("rejected", 1))
    }
}
