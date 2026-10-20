package dk.pantrynanny.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.remote.ApiResult

/** Result of an online call, for screens that show server data (shopping, recipes, ...). */
sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Ok<T>(val value: T) : Load<T>
    data class Failed(val message: String?, val offline: Boolean) : Load<Nothing>
}

fun <T> ApiResult<T>.toLoad(): Load<T> = when (this) {
    is ApiResult.Ok -> Load.Ok(value)
    is ApiResult.NetworkError -> Load.Failed(cause.message, offline = true)
    is ApiResult.HttpError -> Load.Failed(detail ?: "HTTP $code", offline = false)
}

/** Shows a spinner, an error with "try again", or [content] with the loaded value. */
@Composable
fun <T> LoadBox(load: Load<T>, onRetry: () -> Unit, content: @Composable (T) -> Unit) {
    when (load) {
        Load.Loading -> Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
        is Load.Failed -> Column(
            Modifier.fillMaxWidth().padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                stringResource(if (load.offline) R.string.load_offline else R.string.load_failed),
                fontWeight = FontWeight.SemiBold,
            )
            if (!load.offline && load.message != null) {
                Text(load.message, style = MaterialTheme.typography.bodySmall)
            }
            Button(onClick = onRetry) { Text(stringResource(R.string.retry)) }
        }
        is Load.Ok -> content(load.value)
    }
}

/** Title row used by every screen; [onBack] adds a back arrow, [actions] sit on the right. */
@Composable
fun ScreenHeader(
    title: String,
    onBack: (() -> Unit)? = null,
    subtitle: String? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    Row(
        Modifier.fillMaxWidth().padding(start = if (onBack == null) 16.dp else 4.dp, end = 8.dp, top = 8.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back))
            }
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.headlineSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (subtitle != null) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        actions()
    }
}

/** A rounded card with an optional title. */
@Composable
fun SectionCard(
    title: String? = null,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    Card(
        modifier = modifier.fillMaxWidth().let { if (onClick != null) it.clickable(onClick = onClick) else it },
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (title != null) Text(title, style = MaterialTheme.typography.titleMedium)
            content()
        }
    }
}

/** Small coloured label ("mangler", "hjemme", "2 dage"). */
@Composable
fun Pill(text: String, color: Color = MaterialTheme.colorScheme.secondary) {
    Box(
        Modifier
            .background(color.copy(alpha = 0.18f), RoundedCornerShape(50))
            .padding(horizontal = 10.dp, vertical = 3.dp),
    ) {
        Text(text, color = color, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold)
    }
}

/** A tappable list row: optional image, title + subtitle, and something on the right. */
@Composable
fun ListRow(
    title: String,
    subtitle: String? = null,
    imageUrl: String? = null,
    showImage: Boolean = false,
    onClick: (() -> Unit)? = null,
    trailing: @Composable () -> Unit = {},
) {
    Row(
        Modifier
            .fillMaxWidth()
            .let { if (onClick != null) it.clickable(onClick = onClick) else it }
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (showImage) {
            ProductImage(imageUrl, null, Modifier.size(44.dp))
            Spacer(Modifier.width(12.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (!subtitle.isNullOrBlank()) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Spacer(Modifier.width(8.dp))
        trailing()
    }
}

@Composable
fun EmptyText(text: String) {
    Text(
        text,
        modifier = Modifier.fillMaxWidth().padding(24.dp),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@Composable
fun FullScreen(content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxSize(), content = content)
}

/** "2026-10-21" -> "21. okt." (falls back to the raw text). */
fun shortDate(iso: String?): String {
    if (iso.isNullOrBlank()) return ""
    return try {
        val d = java.time.LocalDate.parse(iso.take(10))
        d.format(java.time.format.DateTimeFormatter.ofPattern("d. MMM", java.util.Locale.getDefault()))
    } catch (_: Exception) {
        iso
    }
}

/** Days from today until [iso] (negative = past), or null. */
fun daysUntil(iso: String?): Long? = try {
    iso?.let { java.time.temporal.ChronoUnit.DAYS.between(java.time.LocalDate.now(), java.time.LocalDate.parse(it.take(10))) }
} catch (_: Exception) {
    null
}
