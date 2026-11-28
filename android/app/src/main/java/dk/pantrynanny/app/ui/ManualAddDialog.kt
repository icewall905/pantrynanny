package dk.pantrynanny.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.ProductDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.time.LocalDate

private data class Picked(val id: String, val name: String, val defaultLocationId: String?)

/**
 * Add stock for something without a barcode: pick a product by name (or create one, which needs
 * a connection), then quantity, place and an optional expiry. The stock change itself goes
 * through the same offline queue as scans.
 */
@Composable
fun ManualAddDialog(container: AppContainer, onDismiss: () -> Unit, onDone: (String) -> Unit) {
    val scope = rememberCoroutineScope()
    var query by remember { mutableStateOf("") }
    var picked by remember { mutableStateOf<Picked?>(null) }
    var qty by remember { mutableStateOf("1") }
    var expiry by remember { mutableStateOf("") }
    var locationId by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<Int?>(null) }
    var busy by remember { mutableStateOf(false) }
    val matches by remember(query) {
        container.db.productDao().observeProducts(query.trim().lowercase(), 0, null)
    }.collectAsState(initial = emptyList())
    val locations by remember { container.db.locationDao().observeAll() }.collectAsState(initial = emptyList())
    LaunchedEffect(picked) {
        val p = picked ?: return@LaunchedEffect
        locationId = p.defaultLocationId ?: container.settings.current().defaultLocationId
    }

    fun create() {
        val name = query.trim()
        if (name.isEmpty()) return
        busy = true
        scope.launch {
            val r = container.api.post(
                "api/products",
                buildJsonObject { put("name", JsonPrimitive(name)) },
                ProductDto.serializer(),
            )
            busy = false
            if (r is ApiResult.Ok) {
                container.cache.applyProduct(r.value, 0.0)
                picked = Picked(r.value.id, r.value.name, r.value.defaultLocationId)
                error = null
            } else {
                error = R.string.manual_needs_connection
            }
        }
    }

    fun save() {
        val p = picked ?: return
        val n = qty.trim().replace(',', '.').toDoubleOrNull()
        if (n == null || n <= 0) {
            error = R.string.error_invalid_number
            return
        }
        val exp = expiry.trim().takeIf { it.isNotEmpty() }
        if (exp != null && runCatching { LocalDate.parse(exp) }.isFailure) {
            error = R.string.manual_bad_date
            return
        }
        scope.launch {
            withContext(Dispatchers.IO) {
                container.scanRepository.enqueueOp("add", p.id, n, locationId = locationId, expiresAt = exp)
            }
            container.scanGuard.reset()
            container.requestSync()
            onDone(p.name)
        }
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.manual_add_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                val p = picked
                if (p == null) {
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        label = { Text(stringResource(R.string.manual_name)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (query.isNotBlank()) {
                        LazyColumn(Modifier.heightIn(max = 240.dp)) {
                            items(matches.take(20), key = { it.product.id }) { m ->
                                Text(
                                    m.product.name,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable {
                                            picked = Picked(m.product.id, m.product.name, m.product.defaultLocationId)
                                        }
                                        .padding(vertical = 10.dp),
                                )
                                HorizontalDivider()
                            }
                            item {
                                TextButton(onClick = ::create, enabled = !busy) {
                                    Text(stringResource(R.string.manual_create, query.trim()))
                                }
                            }
                        }
                    }
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(p.name, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        TextButton(onClick = { picked = null }) { Text(stringResource(R.string.manual_change)) }
                    }
                    OutlinedTextField(
                        value = qty,
                        onValueChange = { qty = it },
                        label = { Text(stringResource(R.string.manual_quantity)) },
                        singleLine = true,
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (locations.isNotEmpty()) {
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(6.dp),
                            modifier = Modifier.horizontalScroll(rememberScrollState()),
                        ) {
                            locations.filter { it.deletedAt == null }.forEach { loc ->
                                FilterChip(
                                    selected = locationId == loc.id,
                                    onClick = { locationId = loc.id },
                                    label = { Text(loc.name) },
                                )
                            }
                        }
                    }
                    OutlinedTextField(
                        value = expiry,
                        onValueChange = { expiry = it },
                        label = { Text(stringResource(R.string.manual_expiry)) },
                        placeholder = { Text("2026-12-31") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                error?.let { Text(stringResource(it), color = MaterialTheme.colorScheme.error) }
            }
        },
        confirmButton = {
            TextButton(onClick = ::save, enabled = picked != null) { Text(stringResource(R.string.manual_add)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

