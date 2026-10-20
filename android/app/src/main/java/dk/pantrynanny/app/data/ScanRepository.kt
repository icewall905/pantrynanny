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

/** [undoneClientOpId] is the history op that was undone (null for NOTHING). */
data class UndoOutcome(val result: UndoResult, val undoneClientOpId: String? = null)

data class ScanOutcome(val clientOpId: String, val productId: String?, val known: Boolean)

/**
 * Local-first write path: a scan becomes one pending op plus one history row in a single Room
 * transaction. The displayed quantity (server total + pending deltas) is derived by the DAO
 * queries, so the UI updates as soon as the transaction commits - no network involved.
 */
class ScanRepository(private val db: AppDatabase) {

    suspend fun recordScan(
        raw: String, symbology: String?, mode: ScanMode, locationId: String?,
        /** Called with the new op id inside the transaction, before the rows are inserted, on a cache miss. */
        onCacheMiss: ((String) -> Unit)? = null,
    ): ScanOutcome {
        val norm = BarcodeNormalizer.normalize(raw, symbology)
        return db.withTransaction {
            val pid = db.barcodeDao().productIdForCode(norm.code)
            val product = pid?.let { db.productDao().getWithQty(it) }?.takeIf { it.product.deletedAt == null }
            enqueue(mode.apiType, raw, symbology, product, 1.0, locationId, onCacheMiss)
        }
    }

    /**
     * A lookup / pull found the product behind cache-miss scans of [raw]: link their history rows and, for ops that
     * were not sent yet, the op's product id and optimistic delta so the displayed quantity includes them at once.
     */
    suspend fun linkScans(raw: String, productId: String, name: String) {
        db.withTransaction {
            for (h in db.historyDao().unlinkedByBarcode(raw)) {
                var delta = 0.0
                if (!h.undone && (h.type == "add" || h.type == "remove")) {
                    val d = if (h.type == "remove") {
                        val avail = db.productDao().getWithQty(productId)?.displayQuantity ?: 0.0
                        QuantityMath.clampedRemoveDelta(h.quantity, avail)
                    } else {
                        QuantityMath.signedDelta(h.type, h.quantity)
                    }
                    if (db.pendingOpDao().linkPending(h.clientOpId, productId, d) > 0) delta = d
                }
                db.historyDao().link(h.clientOpId, productId, name, delta)
            }
        }
    }

    /** +/- buttons in the product detail screen. */
    suspend fun adjustProduct(productId: String, mode: ScanMode, locationId: String?): ScanOutcome? =
        db.withTransaction {
            val product = db.productDao().getWithQty(productId) ?: return@withTransaction null
            enqueue(mode.apiType, null, null, product, 1.0, locationId)
        }

    /**
     * +1/+2/+5 on the last-scanned card: one extra op (own client_op_id) for that product/barcode.
     * [type] is the card's own op type ("add"/"remove"), not the scanner's current mode; [symbology]
     * is the original scan's so an unknown barcode normalises to the same code on the server.
     */
    suspend fun addExtra(
        productId: String?, barcode: String, symbology: String?, type: String, quantity: Double, locationId: String?,
        onCacheMiss: ((String) -> Unit)? = null,
    ): ScanOutcome? = db.withTransaction {
        val product = productId?.let { db.productDao().getWithQty(it) }?.takeIf { it.product.deletedAt == null }
        if (product == null && barcode.isEmpty()) return@withTransaction null
        enqueue(type, if (product == null) barcode else null, symbology, product, quantity, locationId, onCacheMiss)
    }

    /**
     * Any stock change made from the app's screens (take out N, move, count, cook a recipe):
     * the same offline queue as scans, so it works without a connection and syncs exactly once.
     * [quantity] is positive, except for "adjust" where it is the signed correction.
     */
    suspend fun enqueueOp(
        type: String,
        productId: String,
        quantity: Double,
        locationId: String? = null,
        toLocationId: String? = null,
    ): ScanOutcome? = db.withTransaction {
        val product = db.productDao().getWithQty(productId) ?: return@withTransaction null
        enqueue(type, null, null, product, quantity, locationId, toLocationId = toLocationId)
    }

    private suspend fun enqueue(
        type: String,
        barcode: String?,
        symbology: String?,
        product: ProductWithQty?,
        quantity: Double,
        locationId: String?,
        onCacheMiss: ((String) -> Unit)? = null,
        toLocationId: String? = null,
    ): ScanOutcome {
        val delta = when {
            product == null -> 0.0
            type == "remove" -> QuantityMath.clampedRemoveDelta(quantity, product.displayQuantity)
            else -> QuantityMath.signedDelta(type, quantity)
        }
        val opId = UUID.randomUUID().toString()
        if (product == null) onCacheMiss?.invoke(opId)
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
                toLocationId = toLocationId,
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
                symbology = symbology,
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
    suspend fun undoLast(): UndoOutcome = undo(null)

    /** Undo one specific op (e.g. "Undo" after cooking a recipe), or the last one when [clientOpId] is null. */
    suspend fun undo(clientOpId: String?): UndoOutcome = db.withTransaction {
        val h = (if (clientOpId == null) db.historyDao().lastUndoable() else db.historyDao().get(clientOpId))
            ?.takeIf { !it.undone } ?: return@withTransaction UndoOutcome(UndoResult.NOTHING)
        db.historyDao().markUndone(h.clientOpId)
        val original = db.pendingOpDao().getByClientOpId(h.clientOpId)
        if (original != null &&
            UndoPlanner.decide(original.status, original.attempts) == UndoAction.DELETE_LOCAL_OP
        ) {
            db.pendingOpDao().deleteByClientOpId(h.clientOpId)
            return@withTransaction UndoOutcome(UndoResult.REMOVED_PENDING, h.clientOpId)
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
        UndoOutcome(UndoResult.QUEUED, h.clientOpId)
    }
}
