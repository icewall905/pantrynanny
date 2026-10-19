package dk.pantrynanny.app.data

import androidx.room.withTransaction
import dk.pantrynanny.app.data.local.AppDatabase
import dk.pantrynanny.app.data.local.BarcodeEntity
import dk.pantrynanny.app.data.local.BatchEntity
import dk.pantrynanny.app.data.local.CategoryEntity
import dk.pantrynanny.app.data.local.LocationEntity
import dk.pantrynanny.app.data.local.PendingOpEntity
import dk.pantrynanny.app.data.local.ProductEntity
import dk.pantrynanny.app.data.remote.CategoryDto
import dk.pantrynanny.app.data.remote.ChangesDto
import dk.pantrynanny.app.data.remote.InventoryEntryDto
import dk.pantrynanny.app.data.remote.LocationDto
import dk.pantrynanny.app.data.remote.OpDto
import dk.pantrynanny.app.data.remote.ProductDto
import dk.pantrynanny.app.data.remote.SnapshotDto

fun ProductDto.toEntity(totalQuantity: Double) = ProductEntity(
    id = id,
    version = version,
    name = name,
    brand = brand,
    categoryId = categoryId,
    defaultLocationId = defaultLocationId,
    imageUrl = imageUrl,
    packageSize = packageSize,
    packageUnit = packageUnit,
    stockUnit = stockUnit,
    minStock = minStock,
    status = status,
    totalQuantity = totalQuantity,
    searchText = (listOfNotNull(name, brand) + aliases).joinToString(" ").lowercase(),
    deletedAt = deletedAt,
)

fun ProductDto.barcodeEntities(): List<BarcodeEntity> =
    barcodes.map { BarcodeEntity(code = it.code, productId = id, raw = it.raw.ifEmpty { it.code }, symbology = it.symbology) }

fun LocationDto.toEntity() = LocationEntity(id, name, icon, sortOrder, isDefault, deletedAt)
fun CategoryDto.toEntity() = CategoryEntity(id, name, icon, color, sortOrder, deletedAt)

fun PendingOpEntity.toDto() = OpDto(
    clientOpId = clientOpId,
    type = type,
    barcode = barcode,
    symbology = symbology,
    productId = productId,
    quantity = quantity,
    locationId = locationId,
    toLocationId = toLocationId,
    expiresAt = expiresAt,
    undoesClientOpId = undoesClientOpId,
    occurredAt = occurredAt,
)

/** Writes server data into the Room cache. Every public function is one DB transaction. */
class CacheWriter(private val db: AppDatabase) {

    /** Upsert a server product, preserving the cached total unless [total] is given. */
    suspend fun applyProduct(dto: ProductDto, total: Double? = null) = db.withTransaction { applyProductInternal(dto, total) }

    private suspend fun applyProductInternal(dto: ProductDto, total: Double?) {
        val existing = db.productDao().get(dto.id)
        db.productDao().upsert(dto.toEntity(total ?: existing?.totalQuantity ?: 0.0))
        if (dto.deletedAt != null) {
            db.barcodeDao().deleteForProduct(dto.id)
        } else if (dto.barcodes.isNotEmpty()) {
            db.barcodeDao().deleteForProduct(dto.id)
            db.barcodeDao().upsertAll(dto.barcodeEntities())
        }
    }

    private suspend fun applyInventory(entries: List<InventoryEntryDto>) {
        for (e in entries) {
            db.productDao().setTotal(e.productId, e.totalQuantity)
            db.batchDao().deleteForProduct(e.productId)
            db.batchDao().insertAll(
                e.batches.map {
                    BatchEntity(
                        id = it.id,
                        productId = e.productId,
                        locationId = it.locationId,
                        quantity = it.quantity,
                        expiresAt = it.expiresAt,
                        openedAt = it.openedAt,
                    )
                }
            )
        }
    }

    /** Replace the whole catalogue cache. Pending ops and scan history are untouched. */
    suspend fun applySnapshot(s: SnapshotDto) = db.withTransaction {
        db.batchDao().clear()
        db.barcodeDao().clear()
        db.productDao().clear()
        db.locationDao().clear()
        db.categoryDao().clear()
        db.locationDao().upsertAll(s.locations.map { it.toEntity() })
        db.categoryDao().upsertAll(s.categories.map { it.toEntity() })
        for (p in s.products) applyProductInternal(p, 0.0)
        applyInventory(s.inventory)
    }

    suspend fun applyChanges(c: ChangesDto) = db.withTransaction {
        db.locationDao().upsertAll(c.locations.map { it.toEntity() })
        db.categoryDao().upsertAll(c.categories.map { it.toEntity() })
        for (p in c.products) applyProductInternal(p, null)
        applyInventory(c.inventory)
    }

    /** Applies the product + total returned for a synced op. */
    suspend fun applyOpProduct(dto: ProductDto, total: Double?) = applyProduct(dto, total)
}
