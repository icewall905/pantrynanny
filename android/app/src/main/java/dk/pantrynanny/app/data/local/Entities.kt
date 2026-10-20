package dk.pantrynanny.app.data.local

import androidx.room.Embedded
import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(tableName = "products", indices = [Index("name"), Index("status")])
data class ProductEntity(
    @PrimaryKey val id: String,
    val version: Int,
    val name: String,
    val brand: String?,
    val categoryId: String?,
    val defaultLocationId: String?,
    val imageUrl: String?,
    val packageSize: Double?,
    val packageUnit: String?,
    val stockUnit: String,
    val minStock: Double?,
    val status: String,
    /** Authoritative server total (sum of batches). Pending local deltas are added at query time. */
    val totalQuantity: Double,
    /** Lower-cased name + brand + aliases for local search. */
    val searchText: String,
    val deletedAt: String?,
)

@Entity(tableName = "barcodes", indices = [Index("productId")])
data class BarcodeEntity(
    /** Normalised code (GTIN-14, "instore:...", "local:...") - unique per household. */
    @PrimaryKey val code: String,
    val productId: String,
    val raw: String,
    val symbology: String?,
)

@Entity(tableName = "batches", indices = [Index("productId"), Index("locationId")])
data class BatchEntity(
    @PrimaryKey val id: String,
    val productId: String,
    val locationId: String?,
    val quantity: Double,
    val expiresAt: String?,
    val openedAt: String?,
)

@Entity(tableName = "locations")
data class LocationEntity(
    @PrimaryKey val id: String,
    val name: String,
    val icon: String?,
    val sortOrder: Int,
    val isDefault: Boolean,
    val deletedAt: String?,
)

@Entity(tableName = "categories")
data class CategoryEntity(
    @PrimaryKey val id: String,
    val name: String,
    val icon: String?,
    val color: String?,
    val sortOrder: Int,
    val deletedAt: String?,
)

/**
 * Persistent operation queue. [seq] gives the upload order.
 * status: pending -> inflight -> (deleted when applied | rejected).
 */
@Entity(tableName = "pending_ops", indices = [Index(value = ["clientOpId"], unique = true), Index("status")])
data class PendingOpEntity(
    @PrimaryKey(autoGenerate = true) val seq: Long = 0,
    val clientOpId: String,
    val type: String,
    val barcode: String?,
    val symbology: String?,
    val productId: String?,
    val quantity: Double,
    val locationId: String?,
    val toLocationId: String?,
    val expiresAt: String?,
    val undoesClientOpId: String?,
    val occurredAt: String,
    /** Optimistic effect on the displayed quantity of [productId]. */
    val localDelta: Double,
    val status: String = STATUS_PENDING,
    val error: String? = null,
    val attempts: Int = 0,
) {
    companion object {
        const val STATUS_PENDING = "pending"
        const val STATUS_INFLIGHT = "inflight"
        const val STATUS_REJECTED = "rejected"
    }
}

@Entity(tableName = "scan_history", indices = [Index("occurredAtMs")])
data class ScanHistoryEntity(
    @PrimaryKey val clientOpId: String,
    val productId: String?,
    val barcode: String,
    val type: String,
    val quantity: Double,
    val localDelta: Double,
    val occurredAtMs: Long,
    val undone: Boolean = false,
    val titleSnapshot: String?,
    /** Symbology of the original scan (null for manual +/- ops); carried to +N extra ops. */
    val symbology: String? = null,
)

data class ProductWithQty(
    @Embedded val product: ProductEntity,
    val displayQuantity: Double,
)

data class HistoryRow(
    @Embedded val entry: ScanHistoryEntity,
    val prodName: String?,
    val prodBrand: String?,
    val prodImageUrl: String?,
    val prodUnit: String?,
    val prodQuantity: Double?,
    val prodStatus: String?,
)
