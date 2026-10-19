package dk.pantrynanny.app.data

import android.content.ContentResolver
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import java.io.ByteArrayOutputStream
import java.io.IOException
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Turns a camera/gallery image into an upload-sized JPEG. Phone photos are often far above the
 * server's 24 MP input limit, so we downscale here (same 1600 px edge the server keeps) and apply
 * the EXIF rotation ourselves, because re-encoding drops the EXIF orientation tag.
 */
object PhotoPrep {
    const val MAX_EDGE = 1600
    private const val JPEG_QUALITY = 85

    /** Largest power-of-two sample size that still leaves the longer edge >= [maxEdge]. */
    fun sampleSizeFor(width: Int, height: Int, maxEdge: Int = MAX_EDGE): Int {
        var sample = 1
        while (max(width, height) / (sample * 2) >= maxEdge) sample *= 2
        return sample
    }

    fun rotationDegrees(exifOrientation: Int): Int = when (exifOrientation) {
        ExifInterface.ORIENTATION_ROTATE_90, ExifInterface.ORIENTATION_TRANSPOSE -> 90
        ExifInterface.ORIENTATION_ROTATE_180, ExifInterface.ORIENTATION_FLIP_VERTICAL -> 180
        ExifInterface.ORIENTATION_ROTATE_270, ExifInterface.ORIENTATION_TRANSVERSE -> 270
        else -> 0
    }

    /** JPEG bytes ready for upload, or null when [uri] is not a decodable image. */
    fun jpegFrom(resolver: ContentResolver, uri: Uri): ByteArray? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        // Bounds-only decoding always returns null; success shows up in outWidth/outHeight.
        resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null

        val opts = BitmapFactory.Options().apply { inSampleSize = sampleSizeFor(bounds.outWidth, bounds.outHeight) }
        val decoded = resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opts) } ?: return null
        val degrees = try {
            resolver.openInputStream(uri)?.use {
                rotationDegrees(ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL))
            } ?: 0
        } catch (e: IOException) {
            0
        }

        val scale = minOf(1f, MAX_EDGE.toFloat() / max(decoded.width, decoded.height))
        val matrix = Matrix().apply {
            postScale(scale, scale)
            postRotate(degrees.toFloat())
        }
        val out = if (scale < 1f || degrees != 0) {
            Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
        } else {
            decoded
        }
        return ByteArrayOutputStream().use { buf ->
            out.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, buf)
            if (out !== decoded) out.recycle()
            decoded.recycle()
            buf.toByteArray()
        }
    }

    /** Decode for display, downsampled so the longer edge is about [maxEdge] px. */
    fun decodeForDisplay(bytes: ByteArray, maxEdge: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        val opts = BitmapFactory.Options().apply { inSampleSize = sampleSizeFor(bounds.outWidth, bounds.outHeight, maxEdge) }
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opts)
    }

    /** Pixel size of the longer edge after [sampleSizeFor] (for tests and logging). */
    fun sampledEdge(width: Int, height: Int, maxEdge: Int = MAX_EDGE): Int =
        (max(width, height).toFloat() / sampleSizeFor(width, height, maxEdge)).roundToInt()
}
