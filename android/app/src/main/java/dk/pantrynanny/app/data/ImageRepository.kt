package dk.pantrynanny.app.data

import android.util.LruCache
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import dk.pantrynanny.app.data.remote.ApiClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Product images for the UI: an in-memory LRU of decoded bitmaps on top of the ApiClient's
 * OkHttp disk cache. Small on purpose; no third-party image library needed for a few hundred thumbnails.
 */
class ImageRepository(private val api: ApiClient) {
    private val memory = object : LruCache<String, ImageBitmap>(MEMORY_BYTES) {
        override fun sizeOf(key: String, value: ImageBitmap): Int = value.width * value.height * 4
    }

    fun cached(url: String): ImageBitmap? = memory.get(url)

    suspend fun load(url: String): ImageBitmap? {
        memory.get(url)?.let { return it }
        val bytes = api.fetchImage(url) ?: return null
        val bitmap = withContext(Dispatchers.Default) { PhotoPrep.decodeForDisplay(bytes, DISPLAY_EDGE) }
            ?.asImageBitmap() ?: return null
        memory.put(url, bitmap)
        return bitmap
    }

    private companion object {
        const val MEMORY_BYTES = 24 * 1024 * 1024
        const val DISPLAY_EDGE = 800
    }
}
