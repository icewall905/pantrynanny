package dk.pantrynanny.app.ui

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import kotlinx.coroutines.launch

/** Everything that is not a daily tab, one tap away. */
@Composable
fun MoreScreen(
    container: AppContainer,
    onOverview: () -> Unit,
    onUnknown: () -> Unit,
    onActivity: () -> Unit,
    onAssistant: () -> Unit,
    onSettings: () -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
        ScreenHeader(stringResource(R.string.nav_more))
        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            MoreItem(Icons.Filled.Home, R.string.nav_overview, R.string.more_overview, onOverview)
            MoreItem(Icons.Filled.Info, R.string.tab_unknown, R.string.more_unknown, onUnknown)
            MoreItem(Icons.Filled.DateRange, R.string.nav_activity, R.string.more_activity, onActivity)
            MoreItem(Icons.Filled.Face, R.string.nav_assistant, R.string.more_assistant, onAssistant)
            MoreItem(Icons.Filled.Settings, R.string.nav_settings, R.string.more_settings, onSettings)
            MoreItem(Icons.AutoMirrored.Filled.ExitToApp, R.string.open_web, R.string.more_web) {
                scope.launch {
                    val base = container.settings.current().serverUrl.trimEnd('/')
                    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, base.toUri())) }
                }
            }
        }
    }
}

@Composable
private fun MoreItem(icon: ImageVector, title: Int, subtitle: Int, onClick: () -> Unit) {
    SectionCard(onClick = onClick) {
        ListItem(
            headlineContent = { Text(stringResource(title)) },
            supportingContent = { Text(stringResource(subtitle)) },
            leadingContent = { Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary) },
            trailingContent = { Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null) },
            colors = ListItemDefaults.colors(containerColor = MaterialTheme.colorScheme.surfaceContainer),
        )
    }
}
