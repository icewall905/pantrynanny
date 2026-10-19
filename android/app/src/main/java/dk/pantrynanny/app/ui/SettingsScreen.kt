package dk.pantrynanny.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.AppSettings
import dk.pantrynanny.app.data.local.LocationEntity
import dk.pantrynanny.app.data.local.PendingOpEntity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class SettingsUiState(
    val settings: AppSettings = AppSettings(),
    val locations: List<LocationEntity> = emptyList(),
    val pending: Int = 0,
    val rejected: List<PendingOpEntity> = emptyList(),
    val syncError: String? = null,
    val syncing: Boolean = false,
)

class SettingsViewModel(private val c: AppContainer) : ViewModel() {
    private val base = combine(
        c.settings.flow,
        c.db.locationDao().observeAll(),
        c.db.pendingOpDao().observePendingCount(),
        c.db.pendingOpDao().observeRejected(),
    ) { s, l, p, r -> SettingsUiState(s, l, p, r) }

    val state: StateFlow<SettingsUiState> = combine(base, c.syncRepository.lastError, c.syncRepository.syncing) { b, e, s ->
        b.copy(syncError = e, syncing = s)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), SettingsUiState())

    fun setSound(on: Boolean) = viewModelScope.launch { c.settings.setSound(on) }
    fun setVibrate(on: Boolean) = viewModelScope.launch { c.settings.setVibrate(on) }
    fun setDefaultLocation(id: String?) = viewModelScope.launch { c.settings.setDefaultLocation(id) }
    fun setRearm(ms: Int?) = viewModelScope.launch { c.settings.setRearmOverride(ms) }
    fun syncNow() = c.syncNowManually()

    fun retryRejected(op: PendingOpEntity) = viewModelScope.launch(Dispatchers.IO) {
        c.db.pendingOpDao().retryRejected(op.seq)
        c.requestSync()
    }

    fun deleteRejected(op: PendingOpEntity) = viewModelScope.launch(Dispatchers.IO) {
        c.db.pendingOpDao().deleteBySeq(op.seq)
    }

    fun logout() = viewModelScope.launch { c.logout() }
}

@Composable
fun SettingsScreen(container: AppContainer) {
    val vm: SettingsViewModel = viewModel(factory = viewModelFactory { initializer { SettingsViewModel(container) } })
    val ui by vm.state.collectAsStateWithLifecycle()
    val s = ui.settings
    var confirmLogout by remember { mutableStateOf(false) }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(stringResource(R.string.nav_settings), style = MaterialTheme.typography.headlineSmall)

        SectionTitle(R.string.section_account)
        Text(stringResource(R.string.server_label, s.serverUrl))
        s.userLabel?.let { Text(stringResource(R.string.user_label, it)) }
        Text(stringResource(R.string.server_url_hint), style = MaterialTheme.typography.bodySmall)
        Button(onClick = {
            if (ui.pending > 0 || ui.rejected.isNotEmpty()) confirmLogout = true else vm.logout()
        }) { Text(stringResource(R.string.logout)) }

        HorizontalDivider()
        SectionTitle(R.string.section_scanning)
        SwitchRow(R.string.setting_sound, s.sound, vm::setSound)
        SwitchRow(R.string.setting_vibrate, s.vibrate, vm::setVibrate)

        Text(stringResource(R.string.setting_default_location))
        Dropdown(
            options = listOf<Pair<String?, String>>(null to stringResource(R.string.none)) +
                ui.locations.map { it.id to it.name },
            selectedId = s.defaultLocationId,
            onSelect = vm::setDefaultLocation,
        )

        var rearm by remember { mutableFloatStateOf(s.effectiveRearmMs.toFloat()) }
        LaunchedEffect(s.effectiveRearmMs) { rearm = s.effectiveRearmMs.toFloat() }
        Text(stringResource(R.string.setting_rearm, rearm.toInt()))
        Slider(
            value = rearm,
            onValueChange = { rearm = it },
            valueRange = 250f..3000f,
            steps = 54,
            onValueChangeFinished = { vm.setRearm(rearm.toInt()) },
        )
        if (s.rearmMsOverride != null) {
            TextButton(onClick = { vm.setRearm(null) }) { Text(stringResource(R.string.setting_rearm_reset, s.serverRearmMs)) }
        }
        Text(stringResource(R.string.setting_remove_timeout, s.serverRemoveTimeoutMin), style = MaterialTheme.typography.bodySmall)

        HorizontalDivider()
        SectionTitle(R.string.section_sync)
        Text(stringResource(R.string.pending_count, ui.pending))
        ui.syncError?.let { Text(stringResource(R.string.sync_error, it), color = MaterialTheme.colorScheme.error) }
        OutlinedButton(onClick = vm::syncNow, enabled = !ui.syncing) {
            Text(stringResource(if (ui.syncing) R.string.syncing else R.string.sync_now))
        }

        if (ui.rejected.isNotEmpty()) {
            SectionTitle(R.string.section_rejected)
            ui.rejected.forEach { op ->
                RejectedRow(op, onRetry = { vm.retryRejected(op) }, onDelete = { vm.deleteRejected(op) })
            }
        }

        HorizontalDivider()
        val context = LocalContext.current
        val version = remember {
            try {
                context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: ""
            } catch (_: Exception) {
                ""
            }
        }
        Text(stringResource(R.string.about_version, version), style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(16.dp))
    }

    if (confirmLogout) {
        AlertDialog(
            onDismissRequest = { confirmLogout = false },
            title = { Text(stringResource(R.string.logout_confirm_title)) },
            text = { Text(stringResource(R.string.logout_confirm_body, ui.pending + ui.rejected.size)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmLogout = false
                    vm.logout()
                }) { Text(stringResource(R.string.logout_confirm_yes)) }
            },
            dismissButton = {
                TextButton(onClick = { confirmLogout = false }) { Text(stringResource(R.string.cancel)) }
            },
        )
    }
}

@Composable
private fun SectionTitle(res: Int) {
    Text(stringResource(res), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
}

@Composable
private fun SwitchRow(labelRes: Int, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(stringResource(labelRes), modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@Composable
private fun RejectedRow(op: PendingOpEntity, onRetry: () -> Unit, onDelete: () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Text("${op.type} × ${op.quantity}  ${op.barcode ?: op.productId ?: ""}", fontWeight = FontWeight.Bold)
        Text(op.error ?: "", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        Row {
            TextButton(onClick = onRetry) { Text(stringResource(R.string.retry)) }
            TextButton(onClick = onDelete) { Text(stringResource(R.string.delete)) }
        }
    }
}
