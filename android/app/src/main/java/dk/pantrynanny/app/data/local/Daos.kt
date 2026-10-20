package dk.pantrynanny.app.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

private const val PENDING_SUM =
    "COALESCE((SELECT SUM(o.localDelta) FROM pending_ops o WHERE o.productId = p.id AND o.status IN ('pending','inflight')), 0.0)"

@Dao
interface ProductDao {
    @Query("SELECT * FROM products WHERE id = :id")
    suspend fun get(id: String): ProductEntity?

    @Upsert
    suspend fun upsert(product: ProductEntity)

    /** The product owning a normalised barcode (a real product before a placeholder); emits again on any change. */
    @Query(
        """
        SELECT p.* FROM products p JOIN barcodes b ON b.productId = p.id
        WHERE b.code = :code AND p.deletedAt IS NULL
        ORDER BY (p.status = 'unknown') LIMIT 1
        """
    )
    fun observeByCode(code: String): Flow<ProductEntity?>

    @Query("UPDATE products SET totalQuantity = :total WHERE id = :id")
    suspend fun setTotal(id: String, total: Double)

    @Query("DELETE FROM products")
    suspend fun clear()

    @Query(
        """
        SELECT p.*, p.totalQuantity + $PENDING_SUM AS displayQuantity
        FROM products p
        WHERE p.deletedAt IS NULL
          AND (:unknownOnly = 0 OR p.status <> 'known')
          AND (:q = '' OR p.searchText LIKE '%' || :q || '%'
               OR p.id IN (SELECT b.productId FROM barcodes b WHERE b.code LIKE '%' || :q || '%' OR b.raw LIKE '%' || :q || '%'))
          AND (:locationId IS NULL
               OR p.id IN (SELECT bt.productId FROM batches bt WHERE bt.locationId = :locationId AND bt.quantity > 0))
        ORDER BY p.name COLLATE NOCASE
        """
    )
    fun observeProducts(q: String, unknownOnly: Int, locationId: String?): Flow<List<ProductWithQty>>

    @Query(
        """
        SELECT p.*, p.totalQuantity + $PENDING_SUM AS displayQuantity
        FROM products p WHERE p.id = :id
        """
    )
    fun observeProduct(id: String): Flow<ProductWithQty?>

    @Query(
        """
        SELECT p.*, p.totalQuantity + $PENDING_SUM AS displayQuantity
        FROM products p WHERE p.id = :id
        """
    )
    suspend fun getWithQty(id: String): ProductWithQty?
}

@Dao
interface BarcodeDao {
    @Query("SELECT productId FROM barcodes WHERE code = :code LIMIT 1")
    suspend fun productIdForCode(code: String): String?

    @Upsert
    suspend fun upsertAll(items: List<BarcodeEntity>)

    @Query("DELETE FROM barcodes WHERE productId = :productId")
    suspend fun deleteForProduct(productId: String)

    @Query("DELETE FROM barcodes")
    suspend fun clear()

    @Query("SELECT * FROM barcodes WHERE productId = :productId ORDER BY code")
    fun observeForProduct(productId: String): Flow<List<BarcodeEntity>>
}

@Dao
interface BatchDao {
    @Query("SELECT * FROM batches WHERE productId = :productId ORDER BY expiresAt IS NULL, expiresAt")
    fun observeForProduct(productId: String): Flow<List<BatchEntity>>

    @Query("DELETE FROM batches WHERE productId = :productId")
    suspend fun deleteForProduct(productId: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(items: List<BatchEntity>)

    @Query("DELETE FROM batches")
    suspend fun clear()
}

@Dao
interface LocationDao {
    @Query("SELECT * FROM locations WHERE deletedAt IS NULL ORDER BY sortOrder, name")
    fun observeAll(): Flow<List<LocationEntity>>

    @Upsert
    suspend fun upsertAll(items: List<LocationEntity>)

    @Query("DELETE FROM locations")
    suspend fun clear()
}

@Dao
interface CategoryDao {
    @Query("SELECT * FROM categories WHERE deletedAt IS NULL ORDER BY sortOrder, name")
    fun observeAll(): Flow<List<CategoryEntity>>

    @Upsert
    suspend fun upsertAll(items: List<CategoryEntity>)

    @Query("DELETE FROM categories")
    suspend fun clear()
}

@Dao
interface PendingOpDao {
    @Insert
    suspend fun insert(op: PendingOpEntity): Long

    @Query("SELECT * FROM pending_ops WHERE status = 'pending' ORDER BY seq LIMIT :limit")
    suspend fun nextPending(limit: Int): List<PendingOpEntity>

    @Query("SELECT * FROM pending_ops WHERE clientOpId = :clientOpId")
    suspend fun getByClientOpId(clientOpId: String): PendingOpEntity?

    /** attempts is incremented BEFORE the request is made: attempts > 0 means "may have reached the server". */
    @Query("UPDATE pending_ops SET status = 'inflight', attempts = attempts + 1 WHERE seq IN (:seqs) AND status = 'pending'")
    suspend fun markInflight(seqs: List<Long>)

    @Query("SELECT * FROM pending_ops WHERE seq IN (:seqs) AND status = 'inflight' ORDER BY seq")
    suspend fun getInflight(seqs: List<Long>): List<PendingOpEntity>

    @Query("UPDATE pending_ops SET status = 'pending' WHERE seq IN (:seqs) AND status = 'inflight'")
    suspend fun revertToPending(seqs: List<Long>)

    @Query("UPDATE pending_ops SET status = 'pending' WHERE status = 'inflight'")
    suspend fun resetInflight()

    /** Give a not-yet-sent barcode op its product + optimistic delta; 0 rows when it was already sent / linked. */
    @Query("UPDATE pending_ops SET productId = :productId, localDelta = :delta WHERE clientOpId = :clientOpId AND status = 'pending' AND productId IS NULL")
    suspend fun linkPending(clientOpId: String, productId: String, delta: Double): Int

    @Query("DELETE FROM pending_ops WHERE clientOpId = :clientOpId")
    suspend fun deleteByClientOpId(clientOpId: String)

    @Query("UPDATE pending_ops SET status = 'rejected', error = :error WHERE clientOpId = :clientOpId")
    suspend fun markRejected(clientOpId: String, error: String)

    @Query("UPDATE pending_ops SET status = 'pending', error = NULL WHERE seq = :seq AND status = 'rejected'")
    suspend fun retryRejected(seq: Long)

    @Query("DELETE FROM pending_ops WHERE seq = :seq")
    suspend fun deleteBySeq(seq: Long)

    @Query("DELETE FROM pending_ops")
    suspend fun clear()

    @Query("SELECT COUNT(*) FROM pending_ops WHERE status IN ('pending','inflight')")
    fun observePendingCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM pending_ops WHERE status IN ('pending','inflight')")
    suspend fun pendingCount(): Int

    @Query("SELECT COUNT(*) FROM pending_ops")
    suspend fun totalOpCount(): Int

    @Query("SELECT * FROM pending_ops WHERE status = 'rejected' ORDER BY seq")
    fun observeRejected(): Flow<List<PendingOpEntity>>
}

@Dao
interface HistoryDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(entry: ScanHistoryEntity)

    @Query("SELECT * FROM scan_history WHERE undone = 0 ORDER BY occurredAtMs DESC LIMIT 1")
    suspend fun lastUndoable(): ScanHistoryEntity?

    @Query("UPDATE scan_history SET undone = 1 WHERE clientOpId = :clientOpId")
    suspend fun markUndone(clientOpId: String)

    @Query("UPDATE scan_history SET productId = :productId, titleSnapshot = :title WHERE clientOpId = :clientOpId AND productId IS NULL")
    suspend fun attachProduct(clientOpId: String, productId: String, title: String)

    @Query("SELECT * FROM scan_history WHERE barcode = :raw AND productId IS NULL ORDER BY occurredAtMs")
    suspend fun unlinkedByBarcode(raw: String): List<ScanHistoryEntity>

    @Query("UPDATE scan_history SET productId = :productId, titleSnapshot = :title, localDelta = :delta WHERE clientOpId = :clientOpId AND productId IS NULL")
    suspend fun link(clientOpId: String, productId: String, title: String, delta: Double)

    /** Link every still-unlinked scan of this raw barcode to a product that was found by lookup/pull. */
    @Query("UPDATE scan_history SET productId = :productId, titleSnapshot = :title WHERE barcode = :raw AND productId IS NULL")
    suspend fun attachProductByBarcode(raw: String, productId: String, title: String)

    /** The product a scan resolved to; null until the op has synced (unknown barcodes get a server placeholder). */
    @Query("SELECT productId FROM scan_history WHERE clientOpId = :clientOpId")
    fun observeProductId(clientOpId: String): Flow<String?>

    @Query("DELETE FROM scan_history WHERE clientOpId NOT IN (SELECT clientOpId FROM scan_history ORDER BY occurredAtMs DESC LIMIT 100)")
    suspend fun trim()

    @Query("DELETE FROM scan_history")
    suspend fun clear()

    @Query(
        """
        SELECT h.*, p.name AS prodName, p.brand AS prodBrand, p.imageUrl AS prodImageUrl, p.stockUnit AS prodUnit,
               p.status AS prodStatus,
               p.totalQuantity + COALESCE((SELECT SUM(o.localDelta) FROM pending_ops o
                    WHERE o.productId = h.productId AND o.status IN ('pending','inflight')), 0.0) AS prodQuantity
        FROM scan_history h LEFT JOIN products p ON p.id = h.productId
        ORDER BY h.occurredAtMs DESC LIMIT :limit
        """
    )
    fun observeRecent(limit: Int): Flow<List<HistoryRow>>
}
