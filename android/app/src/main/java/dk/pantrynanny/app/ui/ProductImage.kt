package dk.pantrynanny.app.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import dk.pantrynanny.app.data.ImageRepository

/** Provided once in MainActivity so any screen can show product images. */
val LocalImages = staticCompositionLocalOf<ImageRepository?> { null }

/** Product photo (cropped to [modifier]'s size); a neutral tile while loading or when there is none. */
@Composable
fun ProductImage(url: String?, contentDescription: String?, modifier: Modifier = Modifier) {
    val images = LocalImages.current
    val bitmap by produceState<ImageBitmap?>(url?.let { images?.cached(it) }, url, images) {
        if (value == null && url != null && images != null) value = images.load(url)
    }
    Box(
        modifier
            .clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant)
    ) {
        bitmap?.let {
            Image(it, contentDescription, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        }
    }
}
