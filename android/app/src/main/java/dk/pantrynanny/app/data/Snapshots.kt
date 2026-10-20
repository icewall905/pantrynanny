package dk.pantrynanny.app.data

import android.content.Context
import android.graphics.Bitmap
import dk.pantrynanny.app.data.local.AppDatabase
import dk.pantrynanny.app.data.remote.ApiClient
import dk.pantrynanny.app.data.remote.ApiResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File

/**
 * Unknown barcodes: the camera frame seen at the scan is kept and uploaded as the product's
 * "snapshot" photo once the server has created the placeholder, so whoever names the product
 * later can see what it was. A snapshot never replaces a real photo; a product image found later
 * replaces it. Files live in app-private storage, named by the scan's op id.
 */
class Snapshots(
    context: Context,
    private val db: AppDatabase,
    private val api: ApiClient,
    private val cache: CacheWriter,
) {
    private val dir = File(context.filesDir, "snapshots")
    private val mutex = Mutex()

    suspend fun keep(clientOpId: String, frame: Bitmap) = withContext(Dispatchers.IO) {
        runCatching {
            dir.mkdirs()
            val scaled = scaleDown(frame, MAX_EDGE)
            File(dir, "$clientOpId.jpg").outputStream().use { scaled.compress(Bitmap.CompressFormat.JPEG, 82, it) }
        }
    }

    /** Upload the kept frames whose product exists by now; stops at the first network error. */
    suspend fun flush() = mutex.withLock {
        withContext(Dispatchers.IO) {
            val files = dir.listFiles { f -> f.name.endsWith(".jpg") }.orEmpty()
            for (f in files) {
                val opId = f.name.removeSuffix(".jpg")
                val productId = db.historyDao().get(opId)?.productId
                if (productId == null) {
                    if (System.currentTimeMillis() - f.lastModified() > MAX_AGE_MS) f.delete()
                    continue // the scan has not synced yet
                }
                val product = db.productDao().get(productId)
                if (product == null || product.imageUrl != null) {
                    f.delete()
                    continue
                }
                when (val r = api.uploadPhoto(productId, f.readBytes(), snapshot = true)) {
                    is ApiResult.Ok -> {
                        cache.applyProduct(r.value)
                        f.delete()
                    }
                    is ApiResult.HttpError -> f.delete() // product gone or image refused: give up on it
                    is ApiResult.NetworkError -> return@withContext
                }
            }
        }
    }

    companion object {
        private const val MAX_EDGE = 1280
        private const val MAX_AGE_MS = 7L * 24 * 3600 * 1000

        fun scaleDown(b: Bitmap, maxEdge: Int): Bitmap {
            val edge = maxOf(b.width, b.height)
            if (edge <= maxEdge) return b
            val f = maxEdge.toFloat() / edge
            return Bitmap.createScaledBitmap(b, (b.width * f).toInt(), (b.height * f).toInt(), true)
        }
    }
}
