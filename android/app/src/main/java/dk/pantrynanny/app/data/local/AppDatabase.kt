package dk.pantrynanny.app.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

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
    version = 2,
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

object Migrations {
    /** v2: scan_history.symbology (nullable; existing rows keep null = "unknown symbology"). */
    const val ADD_HISTORY_SYMBOLOGY = "ALTER TABLE scan_history ADD COLUMN symbology TEXT"

    val MIGRATION_1_2 = object : Migration(1, 2) {
        override fun migrate(db: SupportSQLiteDatabase) {
            db.execSQL(ADD_HISTORY_SYMBOLOGY)
        }
    }
}
