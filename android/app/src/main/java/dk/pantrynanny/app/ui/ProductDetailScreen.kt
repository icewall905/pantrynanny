package dk.pantrynanny.app.ui

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.pm.PackageManager
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.EditResult
import dk.pantrynanny.app.data.PhotoFiles
import dk.pantrynanny.app.data.PhotoPrep
import dk.pantrynanny.app.data.local.BarcodeEntity
import dk.pantrynanny.app.data.local.BatchEntity
import dk.pantrynanny.app.data.local.CategoryEntity
import dk.pantrynanny.app.data.local.LocationEntity
import dk.pantrynanny.app.data.local.ProductWithQty
import dk.pantrynanny.app.domain.QuantityMath
import dk.pantrynanny.app.domain.ScanMode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class DetailUiState(
    val product: ProductWithQty? = null,
    val barcodes: List<BarcodeEntity> = emptyList(),
    val batches: List<BatchEntity> = emptyList(),
    val locations: List<LocationEntity> = emptyList(),
    val categories: List<CategoryEntity> = emptyList(),
)

class ProductDetailViewModel(private val c: AppContainer, private val productId: String) : ViewModel() {
    private val barcodeBatches = combine(
        c.db.barcodeDao().observeForProduct(productId),
        c.db.batchDao().observeForProduct(productId),
    ) { b, bt -> b to bt }

    private val refs = combine(c.db.locationDao().observeAll(), c.db.categoryDao().observeAll()) { l, cat -> l to cat }

    val state: StateFlow<DetailUiState> = combine(
        c.db.productDao().observeProduct(productId), barcodeBatches, refs,
    ) { p, bb, r ->
        DetailUiState(p, bb.first, bb.second, r.first, r.second)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), DetailUiState())

    private val _events = MutableSharedFlow<UiMessage>(extraBufferCapacity = 8)
    val events: SharedFlow<UiMessage> = _events.asSharedFlow()

    private val _uploading = MutableStateFlow(false)
    val uploading: StateFlow<Boolean> = _uploading.asStateFlow()

    /** Shrink, rotate and upload a camera/gallery image as this product's photo. */
    fun uploadPhoto(uri: Uri) {
        if (_uploading.value) return
        _uploading.value = true
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val jpeg = PhotoPrep.jpegFrom(c.app.contentResolver, uri)
                if (jpeg == null) {
                    _events.tryEmit(UiMessage(R.string.photo_invalid))
                    return@launch
                }
                when (val r = c.inventoryRepository.uploadPhoto(productId, jpeg)) {
                    EditResult.Saved -> _events.tryEmit(UiMessage(R.string.photo_saved))
                    EditResult.Offline -> _events.tryEmit(UiMessage(R.string.photo_offline))
                    is EditResult.Failed -> _events.tryEmit(UiMessage(R.string.edit_failed, r.message))
                    else -> Unit
                }
            } catch (e: SecurityException) {
                _events.tryEmit(UiMessage(R.string.photo_invalid))
            } finally {
                PhotoFiles.cleanUp(c.app)
                _uploading.value = false
            }
        }
    }

    /** +/- go through the same op queue as scans. */
    fun adjust(mode: ScanMode) {
        viewModelScope.launch(Dispatchers.IO) {
            val product = state.value.product?.product
            val loc = product?.defaultLocationId ?: c.settings.current().defaultLocationId
            c.scanRepository.adjustProduct(productId, mode, loc)
            c.scanGuard.reset() // the last-scanned card is no longer the last op
            c.requestSync()
        }
    }

    fun save(name: String, brand: String, categoryId: String?, minStock: String, defaultLocationId: String?, onSaved: () -> Unit) {
        val current = state.value.product?.product ?: return
        val min = minStock.trim().replace(',', '.').takeIf { it.isNotEmpty() }?.toDoubleOrNull()
        if (minStock.isNotBlank() && min == null) {
            _events.tryEmit(UiMessage(R.string.error_invalid_number))
            return
        }
        if (name.isBlank()) {
            _events.tryEmit(UiMessage(R.string.error_name_required))
            return
        }
        viewModelScope.launch {
            val result = c.inventoryRepository.editProduct(
                current, name.trim(), brand.trim().ifEmpty { null }, categoryId, min, defaultLocationId,
            )
            when (result) {
                EditResult.Saved -> {
                    _events.tryEmit(UiMessage(R.string.edit_saved))
                    onSaved()
                }
                EditResult.NothingChanged -> onSaved()
                EditResult.Conflict -> _events.tryEmit(UiMessage(R.string.edit_conflict))
                EditResult.Offline -> _events.tryEmit(UiMessage(R.string.edit_offline))
                is EditResult.Failed -> _events.tryEmit(UiMessage(R.string.edit_failed, result.message))
            }
        }
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
@Composable
fun ProductDetailScreen(
    container: AppContainer,
    productId: String,
    snackbar: SnackbarHostState,
    onBack: () -> Unit,
    /** Opened from the scanner's "Registrer": start in the edit form and return to scanning after save/cancel. */
    register: Boolean = false,
) {
    val vm: ProductDetailViewModel = viewModel(
        key = "product-$productId",
        factory = viewModelFactory { initializer { ProductDetailViewModel(container, productId) } },
    )
    val ui by vm.state.collectAsStateWithLifecycle()
    val uploading by vm.uploading.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    LaunchedEffect(vm) {
        vm.events.collect { msg ->
            snackbar.currentSnackbarData?.dismiss()
            scope.launch { snackbar.showSnackbar(msg.resolve(context), duration = SnackbarDuration.Short) }
        }
    }

    val item = ui.product
    var editing by remember { mutableStateOf(register) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) {
        IconButton(onClick = onBack) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back))
        }
        if (item == null) {
            Text(stringResource(R.string.product_not_found))
            return@Column
        }
        val p = item.product

        if (!editing) {
            PhotoSection(p.imageUrl, p.name, uploading, onPhoto = vm::uploadPhoto)
            Spacer(Modifier.height(8.dp))
            Text(p.name, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            p.brand?.takeIf { it.isNotBlank() }?.let { Text(it) }
            if (p.status != "known") {
                Text(stringResource(R.string.status_unknown_badge), color = WarnColor, fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                OutlinedButton(onClick = { vm.adjust(ScanMode.REMOVE) }, modifier = Modifier.size(64.dp)) {
                    Text("−", fontSize = 28.sp)
                }
                Text(
                    stringResource(R.string.quantity_with_unit, QuantityMath.format(maxOf(item.displayQuantity, 0.0)), unitLabel(p.stockUnit)),
                    fontSize = 28.sp,
                    fontWeight = FontWeight.Bold,
                )
                OutlinedButton(onClick = { vm.adjust(ScanMode.ADD) }, modifier = Modifier.size(64.dp)) {
                    Text("+", fontSize = 28.sp)
                }
            }
            if (QuantityMath.isLowStock(item.displayQuantity, p.minStock)) {
                Text(stringResource(R.string.low_stock), color = WarnColor)
            }
            p.minStock?.let { Text(stringResource(R.string.min_stock_value, QuantityMath.format(it))) }

            Spacer(Modifier.height(12.dp))
            if (ui.barcodes.isNotEmpty()) {
                Text(stringResource(R.string.barcodes), fontWeight = FontWeight.Bold)
                ui.barcodes.forEach { Text(it.raw.ifEmpty { it.code }) }
                Spacer(Modifier.height(12.dp))
            }

            Text(stringResource(R.string.batches), fontWeight = FontWeight.Bold)
            if (ui.batches.isEmpty()) Text(stringResource(R.string.no_batches))
            ui.batches.forEach { b ->
                val loc = ui.locations.firstOrNull { it.id == b.locationId }?.name ?: "-"
                Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                    Text(loc, modifier = Modifier.weight(1f))
                    Text(b.expiresAt?.let { stringResource(R.string.expires, it) } ?: "", modifier = Modifier.padding(end = 12.dp))
                    Text(QuantityMath.format(b.quantity), fontWeight = FontWeight.Bold)
                }
                HorizontalDivider()
            }
            Spacer(Modifier.height(16.dp))
            Button(onClick = { editing = true }) { Text(stringResource(R.string.edit)) }
        } else {
            if (p.status == "unknown") {
                Text(stringResource(R.string.register_title), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                ui.barcodes.firstOrNull()?.let { Text(stringResource(R.string.register_barcode, it.raw.ifEmpty { it.code })) }
                Spacer(Modifier.height(8.dp))
            }
            PhotoSection(p.imageUrl, p.name, uploading, onPhoto = vm::uploadPhoto)
            Spacer(Modifier.height(8.dp))
            EditForm(
                key = p.id + ":" + p.version,
                item = item,
                ui = ui,
                onCancel = { if (register) onBack() else editing = false },
                onSave = { name, brand, cat, min, loc ->
                    vm.save(name, brand, cat, min, loc) { if (register) onBack() else editing = false }
                },
            )
        }
    }
}

/** Product photo plus "take photo" (camera app) / "choose photo" (system photo picker, no permission). */
@Composable
private fun PhotoSection(imageUrl: String?, name: String, uploading: Boolean, onPhoto: (Uri) -> Unit) {
    val context = LocalContext.current
    var pendingUri by rememberSaveable { mutableStateOf<String?>(null) }
    val takePicture = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val uri = pendingUri
        pendingUri = null
        if (ok && uri != null) onPhoto(Uri.parse(uri))
    }
    val launchCamera = {
        val uri = PhotoFiles.newCaptureUri(context)
        pendingUri = uri.toString()
        try {
            takePicture.launch(uri)
        } catch (e: ActivityNotFoundException) {
            pendingUri = null
            Toast.makeText(context, R.string.photo_no_camera, Toast.LENGTH_SHORT).show()
        }
    }
    // The app declares CAMERA (for the scanner), so the camera intent needs it granted too.
    val cameraPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) launchCamera()
    }
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) onPhoto(uri)
    }

    if (imageUrl != null) {
        ProductImage(imageUrl, name, Modifier.fillMaxWidth().height(200.dp))
        Spacer(Modifier.height(8.dp))
    }
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
        OutlinedButton(
            enabled = !uploading,
            onClick = {
                val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) ==
                    PackageManager.PERMISSION_GRANTED
                if (granted) launchCamera() else cameraPermission.launch(Manifest.permission.CAMERA)
            },
        ) { Text(stringResource(if (imageUrl == null) R.string.photo_take else R.string.photo_retake)) }
        OutlinedButton(
            enabled = !uploading,
            onClick = { pick.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
        ) { Text(stringResource(R.string.photo_choose)) }
        if (uploading) Text(stringResource(R.string.photo_uploading))
    }
}

@Composable
private fun EditForm(
    key: String,
    item: ProductWithQty,
    ui: DetailUiState,
    onCancel: () -> Unit,
    onSave: (String, String, String?, String, String?) -> Unit,
) {
    val p = item.product
    // An unknown product still carries the server placeholder name ("Ukendt vare <barcode>"): start empty.
    var name by remember(key) { mutableStateOf(if (p.status == "unknown") "" else p.name) }
    var brand by remember(key) { mutableStateOf(p.brand ?: "") }
    var minStock by remember(key) { mutableStateOf(p.minStock?.let { QuantityMath.format(it) } ?: "") }
    var categoryId by remember(key) { mutableStateOf(p.categoryId) }
    var locationId by remember(key) { mutableStateOf(p.defaultLocationId) }
    val none = stringResource(R.string.none)

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(
            value = name, onValueChange = { name = it }, singleLine = true,
            label = { Text(stringResource(R.string.field_name)) }, modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = brand, onValueChange = { brand = it }, singleLine = true,
            label = { Text(stringResource(R.string.field_brand)) }, modifier = Modifier.fillMaxWidth(),
        )
        Text(stringResource(R.string.field_category))
        Dropdown(
            options = listOf<Pair<String?, String>>(null to none) + ui.categories.map { it.id to it.name },
            selectedId = categoryId,
            onSelect = { categoryId = it },
        )
        OutlinedTextField(
            value = minStock, onValueChange = { minStock = it }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            label = { Text(stringResource(R.string.field_min_stock)) }, modifier = Modifier.fillMaxWidth(),
        )
        Text(stringResource(R.string.field_default_location))
        Dropdown(
            options = listOf<Pair<String?, String>>(null to none) + ui.locations.map { it.id to it.name },
            selectedId = locationId,
            onSelect = { locationId = it },
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onSave(name, brand, categoryId, minStock, locationId) }) { Text(stringResource(R.string.save)) }
            TextButton(onClick = onCancel) { Text(stringResource(R.string.cancel)) }
        }
    }
}
