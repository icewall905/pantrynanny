package dk.pantrynanny.app.data

import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File

/** Temporary files the camera app writes product photos into (shared via the `.photos` FileProvider). */
object PhotoFiles {
    private fun dir(context: Context): File = File(context.cacheDir, "photos").apply { mkdirs() }

    fun newCaptureUri(context: Context): Uri {
        val file = File.createTempFile("product-", ".jpg", dir(context))
        return FileProvider.getUriForFile(context, "${context.packageName}.photos", file)
    }

    /** Captures are only needed until they are uploaded. */
    fun cleanUp(context: Context) {
        dir(context).listFiles()?.forEach { it.delete() }
    }
}
