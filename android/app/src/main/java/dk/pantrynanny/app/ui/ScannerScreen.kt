package dk.pantrynanny.app.ui

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.local.HistoryRow
import dk.pantrynanny.app.domain.CardPhase
import dk.pantrynanny.app.domain.QuantityMath
import dk.pantrynanny.app.domain.ScanMode
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val timeFormat: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm:ss")

private fun hasCameraPermission(context: Context) =
    ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

@Composable
fun ScannerScreen(vm: ScannerViewModel, snackbar: SnackbarHostState, onRegisterProduct: (String) -> Unit) {
    val state by vm.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    KeepScreenOn()

    LaunchedEffect(vm) {
        vm.events.collect { msg ->
            snackbar.currentSnackbarData?.dismiss()
            scope.launch { snackbar.showSnackbar(msg.resolve(context), duration = SnackbarDuration.Short) }
        }
    }
    LaunchedEffect(vm) {
        vm.unknownScans.collect { clientOpId ->
            snackbar.currentSnackbarData?.dismiss()
            scope.launch {
                val result = snackbar.showSnackbar(
                    context.getString(R.string.snack_unknown),
                    actionLabel = context.getString(R.string.action_register),
                    duration = SnackbarDuration.Long,
                )
                if (result == SnackbarResult.ActionPerformed) vm.register(clientOpId)
            }
        }
    }
    LaunchedEffect(vm) {
        vm.openForRegister.collect { onRegisterProduct(it) }
    }

    var granted by remember { mutableStateOf(hasCameraPermission(context)) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) granted = hasCameraPermission(context)
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    LaunchedEffect(Unit) {
        if (!granted) launcher.launch(Manifest.permission.CAMERA)
    }

    val accent = if (state.mode == ScanMode.ADD) AddColor else RemoveColor

    Column(
        Modifier
            .fillMaxSize()
            .border(6.dp, accent)
            .padding(6.dp)
    ) {
        StatusRow(state.status)

        Box(
            Modifier
                .fillMaxWidth()
                .weight(1f)
                .clip(RoundedCornerShape(20.dp))
                .background(Color.Black)
        ) {
            if (granted) {
                var canSwitch by remember { mutableStateOf(false) }
                CameraPreview(
                    torchOn = state.torch,
                    onBarcode = vm::onDecoded,
                    modifier = Modifier.fillMaxSize(),
                    frontCamera = state.frontCamera,
                    otherFormats = state.otherFormats,
                    onCanSwitch = { canSwitch = it },
                )
                Row(Modifier.align(Alignment.TopEnd)) {
                    if (canSwitch) {
                        TextButton(onClick = vm::toggleCamera) {
                            Text(
                                stringResource(if (state.frontCamera) R.string.camera_use_rear else R.string.camera_use_front),
                                color = Color.White,
                            )
                        }
                    }
                    // Front cameras have no torch.
                    if (!state.frontCamera) {
                        TextButton(onClick = vm::toggleTorch) {
                            Text(
                                stringResource(if (state.torch) R.string.torch_on else R.string.torch_off),
                                color = Color.White,
                            )
                        }
                    }
                }
            } else {
                CameraPermissionRationale(
                    onRequest = { launcher.launch(Manifest.permission.CAMERA) },
                    onOpenSettings = {
                        context.startActivity(
                            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
                                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        )
                    },
                )
            }
            Text(
                text = stringResource(if (state.mode == ScanMode.ADD) R.string.mode_add_banner else R.string.mode_remove_banner),
                color = Color.White,
                fontWeight = FontWeight.Bold,
                modifier = Modifier
                    .align(Alignment.TopStart)
                    .padding(8.dp)
                    .background(accent, RoundedCornerShape(6.dp))
                    .padding(horizontal = 10.dp, vertical = 4.dp),
            )
        }

        Spacer(Modifier.height(6.dp))
        ModeToggle(state.mode, onSelect = vm::setMode)
        Spacer(Modifier.height(6.dp))
        LastScanCard(state.last, state.lastPhase, accent, state.alreadyCounted, onRegister = vm::register, onExtra = vm::addExtra)
        Spacer(Modifier.height(4.dp))

        LazyColumn(
            Modifier
                .fillMaxWidth()
                .weight(0.7f)
        ) {
            items(state.history, key = { it.entry.clientOpId }) { row ->
                HistoryItem(row, onRegister = vm::register)
                HorizontalDivider()
            }
        }

        OutlinedButton(
            onClick = vm::undo,
            enabled = state.history.any { !it.entry.undone },
            modifier = Modifier
                .fillMaxWidth()
                .height(48.dp),
        ) { Text(stringResource(R.string.undo_last)) }
    }
}

@Composable
private fun StatusRow(status: SyncStatusUi) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 4.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val (connText, connColor) = when {
            !status.online -> stringResource(R.string.status_offline) to WarnColor
            status.serverProblem -> stringResource(R.string.status_server_down) to RemoveColor
            else -> stringResource(R.string.status_online) to AddColor
        }
        Text(connText, color = connColor, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (status.rejected > 0) {
                Text(
                    stringResource(R.string.rejected_count, status.rejected),
                    color = WarnColor,
                    fontWeight = FontWeight.Bold,
                    fontSize = 14.sp,
                )
                Spacer(Modifier.padding(horizontal = 6.dp))
            }
            val text = when {
                status.pending > 0 -> stringResource(R.string.pending_count, status.pending)
                status.syncing -> stringResource(R.string.syncing)
                else -> stringResource(R.string.all_synced)
            }
            Text(text, fontSize = 14.sp)
        }
    }
}

@Composable
private fun ModeToggle(mode: ScanMode, onSelect: (ScanMode) -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        ModeButton(
            label = stringResource(R.string.mode_add),
            selected = mode == ScanMode.ADD,
            color = AddColor,
            onClick = { onSelect(ScanMode.ADD) },
            modifier = Modifier.weight(1f),
        )
        ModeButton(
            label = stringResource(R.string.mode_remove),
            selected = mode == ScanMode.REMOVE,
            color = RemoveColor,
            onClick = { onSelect(ScanMode.REMOVE) },
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun ModeButton(
    label: String,
    selected: Boolean,
    color: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Button(
        onClick = onClick,
        modifier = modifier.height(84.dp),
        shape = RoundedCornerShape(20.dp),
        colors = if (selected) {
            ButtonDefaults.buttonColors(containerColor = color, contentColor = Color.White)
        } else {
            ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        },
    ) {
        Text(label, fontSize = 28.sp, fontWeight = FontWeight.ExtraBold)
    }
}

@Composable
private fun rowTitle(row: HistoryRow): String =
    row.prodName ?: row.entry.titleSnapshot
        ?: if (row.entry.barcode.isNotEmpty()) stringResource(R.string.unknown_product_with_code, row.entry.barcode)
        else stringResource(R.string.unknown_product)

/** An unknown barcode that still needs a name (not synced yet, or synced to a server placeholder). */
private fun needsRegister(row: HistoryRow): Boolean =
    row.entry.barcode.isNotEmpty() && !row.entry.undone && (row.prodStatus == null || row.prodStatus == "unknown")

@Composable
private fun LastScanCard(
    last: HistoryRow?,
    phase: CardPhase,
    accent: Color,
    alreadyCounted: Boolean,
    onRegister: (String) -> Unit,
    onExtra: (HistoryRow, Int) -> Unit,
) {
    Card(
        Modifier
            .fillMaxWidth()
            .then(
                if (alreadyCounted) Modifier.border(3.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(12.dp))
                else Modifier
            ),
    ) {
        Column(Modifier.padding(10.dp)) {
            if (last == null) {
                Text(stringResource(R.string.scan_prompt), fontSize = 18.sp)
            } else {
                val sign = if (last.entry.type == "add") "+" else "−"
                Row(verticalAlignment = Alignment.CenterVertically) {
                    if (last.prodImageUrl != null) {
                        ProductImage(last.prodImageUrl, rowTitle(last), Modifier.size(56.dp))
                        Spacer(Modifier.padding(horizontal = 4.dp))
                    }
                    Text(
                        "$sign${QuantityMath.format(last.entry.quantity)}",
                        color = accent,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.ExtraBold,
                    )
                    Spacer(Modifier.padding(horizontal = 6.dp))
                    Column(Modifier.weight(1f)) {
                        if (phase == CardPhase.LOOKING || phase == CardPhase.SLOW) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                if (phase == CardPhase.LOOKING) {
                                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                                    Spacer(Modifier.padding(horizontal = 4.dp))
                                }
                                Text(
                                    stringResource(if (phase == CardPhase.LOOKING) R.string.lookup_looking else R.string.lookup_slow),
                                    fontSize = 20.sp,
                                    fontWeight = FontWeight.Bold,
                                    maxLines = 1,
                                )
                            }
                        } else Text(
                            rowTitle(last),
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold,
                            maxLines = 1,
                            textDecoration = if (last.entry.undone) TextDecoration.LineThrough else null,
                        )
                        last.prodBrand?.takeIf { it.isNotBlank() }?.let { Text(it, fontSize = 14.sp, maxLines = 1) }
                    }
                    last.prodQuantity?.let { q ->
                        Text(
                            stringResource(R.string.quantity_with_unit, QuantityMath.format(maxOf(q, 0.0)), unitLabel(last.prodUnit)),
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }
                if (alreadyCounted) {
                    Text(
                        stringResource(R.string.already_counted),
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(top = 6.dp),
                    )
                }
                if (!last.entry.undone) {
                    Row(Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        for (n in intArrayOf(1, 2, 5)) {
                            OutlinedButton(onClick = { onExtra(last, n) }, modifier = Modifier.weight(1f)) {
                                Text("+$n", fontSize = 18.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                }
                if (needsRegister(last) && phase != CardPhase.LOOKING) {
                    Button(
                        onClick = { onRegister(last.entry.clientOpId) },
                        modifier = Modifier.fillMaxWidth().padding(top = 6.dp),
                    ) { Text(stringResource(R.string.register_now)) }
                }
            }
        }
    }
}

@Composable
private fun HistoryItem(row: HistoryRow, onRegister: (String) -> Unit) {
    val time = timeFormat.format(Instant.ofEpochMilli(row.entry.occurredAtMs).atZone(ZoneId.systemDefault()))
    val sign = if (row.entry.type == "add") "+" else "−"
    val color = if (row.entry.type == "add") AddColor else RemoveColor
    val register = needsRegister(row)
    Row(
        Modifier
            .fillMaxWidth()
            .then(if (register) Modifier.clickable { onRegister(row.entry.clientOpId) } else Modifier)
            .padding(vertical = 4.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(time, fontSize = 12.sp, modifier = Modifier.padding(end = 8.dp))
        Text(sign, color = color, fontWeight = FontWeight.Bold, modifier = Modifier.padding(end = 8.dp))
        Text(
            rowTitle(row),
            modifier = Modifier.weight(1f),
            maxLines = 1,
            textDecoration = if (row.entry.undone) TextDecoration.LineThrough else null,
        )
        if (register) {
            Text(stringResource(R.string.action_register), color = WarnColor, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        } else {
            row.prodQuantity?.let { Text(QuantityMath.format(maxOf(it, 0.0)), fontWeight = FontWeight.Bold) }
        }
    }
}

@Composable
private fun CameraPermissionRationale(onRequest: () -> Unit, onOpenSettings: () -> Unit) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(stringResource(R.string.perm_title), color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(12.dp))
        Text(stringResource(R.string.perm_body), color = Color.White)
        Spacer(Modifier.height(16.dp))
        Button(onClick = onRequest) { Text(stringResource(R.string.perm_grant)) }
        TextButton(onClick = onOpenSettings) { Text(stringResource(R.string.perm_open_settings)) }
    }
}
