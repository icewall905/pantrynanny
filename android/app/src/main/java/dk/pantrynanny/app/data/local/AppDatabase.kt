package dk.pantrynanny.app.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [
        ProductEntity::class,
        BarcodeEntity::class,
        BatchEntity::class,
        LocationEntity::class,
        CategoryEntity::class,
        PendingOpEntity::class,
        ScanHistoryEntity::class,
    ],
    version = 1,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun productDao(): ProductDao
    abstract fun barcodeDao(): BarcodeDao
    abstract fun batchDao(): BatchDao
    abstract fun locationDao(): LocationDao
    abstract fun categoryDao(): CategoryDao
    abstract fun pendingOpDao(): PendingOpDao
    abstract fun historyDao(): HistoryDao
}
