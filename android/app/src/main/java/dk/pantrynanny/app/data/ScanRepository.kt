package dk.pantrynanny.app.data

import androidx.room.withTransaction
import dk.pantrynanny.app.data.local.AppDatabase
import dk.pantrynanny.app.data.local.PendingOpEntity
import dk.pantrynanny.app.data.local.ProductWithQty
import dk.pantrynanny.app.data.local.ScanHistoryEntity
import dk.pantrynanny.app.domain.BarcodeNormalizer
import dk.pantrynanny.app.domain.QuantityMath
import dk.pantrynanny.app.domain.ScanMode
import dk.pantrynanny.app.domain.UndoAction
import dk.pantrynanny.app.domain.UndoPlanner
import java.time.Instant
import java.util.UUID

enum class UndoResult { NOTHING, REMOVED_PENDING, QUEUED }

data class ScanOutcome(val clientOpId: String, val productId: String?, val known: Boolean)

/**
 * Local-first write path: a scan becomes one pending op plus one history row in a single Room
 * transaction. The displayed quantity (server total + pending deltas) is derived by the DAO
 * queries, so the UI updates as soon as the transaction commits - no network involved.
 */
class ScanRepository(private val db: AppDatabase) {

    suspend fun recordScan(raw: String, symbology: String?, mode: ScanMode, locationId: String?): ScanOutcome {
        val norm = BarcodeNormalizer.normalize(raw, symbology)
        return db.withTransaction {
            val pid = db.barcodeDao().productIdForCode(norm.code)
            val product = pid?.let { db.productDao().getWithQty(it) }?.takeIf { it.product.deletedAt == null }
            enqueue(mode.apiType, raw, symbology, product, 1.0, locationId)
        }
    }

    /** +/- buttons in the product detail screen. */
    suspend fun adjustProduct(productId: String, mode: ScanMode, locationId: String?): ScanOutcome? =
        db.withTransaction {
            val product = db.productDao().getWithQty(productId) ?: return@withTransaction null
            enqueue(mode.apiType, null, null, product, 1.0, locationId)
        }

    private suspend fun enqueue(
        type: String,
        barcode: String?,
        symbology: String?,
        product: ProductWithQty?,
        quantity: Double,
        locationId: String?,
    ): ScanOutcome {
        val delta = when {
            product == null -> 0.0
            type == "remove" -> QuantityMath.clampedRemoveDelta(quantity, product.displayQuantity)
            else -> QuantityMath.signedDelta(type, quantity)
        }
        val opId = UUID.randomUUID().toString()
        val now = Instant.now()
        db.pendingOpDao().insert(
            PendingOpEntity(
                clientOpId = opId,
                type = type,
                barcode = barcode,
                symbology = symbology,
                productId = product?.product?.id,
                quantity = quantity,
                locationId = locationId,
                toLocationId = null,
                expiresAt = null,
                undoesClientOpId = null,
                occurredAt = now.toString(),
                localDelta = delta,
            )
        )
        db.historyDao().insert(
            ScanHistoryEntity(
                clientOpId = opId,
                productId = product?.product?.id,
                barcode = barcode ?: "",
                type = type,
                quantity = quantity,
                localDelta = delta,
                occurredAtMs = now.toEpochMilli(),
                titleSnapshot = product?.product?.name,
            )
        )
        db.historyDao().trim()
        // A cached server placeholder (status "unknown") still needs registering, same rule as the web app.
        return ScanOutcome(opId, product?.product?.id, known = product != null && product.product.status != "unknown")
    }

    /**
     * Undo the most recent non-undone scan: a still-pending op is simply deleted; an op that is
     * in flight or already synced gets a compensating `undo` op referencing its client_op_id.
     */
    suspend fun undoLast(): UndoResult = db.withTransaction {
        val h = db.historyDao().lastUndoable() ?: return@withTransaction UndoResult.NOTHING
        db.historyDao().markUndone(h.clientOpId)
        val original = db.pendingOpDao().getByClientOpId(h.clientOpId)
        if (original != null &&
            UndoPlanner.decide(original.status, original.attempts) == UndoAction.DELETE_LOCAL_OP
        ) {
            db.pendingOpDao().deleteByClientOpId(h.clientOpId)
            return@withTransaction UndoResult.REMOVED_PENDING
        }
        db.pendingOpDao().insert(
            PendingOpEntity(
                clientOpId = UUID.randomUUID().toString(),
                type = "undo",
                barcode = null,
                symbology = null,
                productId = h.productId,
                quantity = h.quantity,
                locationId = null,
                toLocationId = null,
                expiresAt = null,
                undoesClientOpId = h.clientOpId,
                occurredAt = Instant.now().toString(),
                localDelta = -h.localDelta,
            )
        )
        UndoResult.QUEUED
    }
}
