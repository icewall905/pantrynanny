package dk.pantrynanny.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.InventoryItemDto
import dk.pantrynanny.app.data.remote.ShoppingItemDto
import dk.pantrynanny.app.domain.QuantityMath
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

data class ShoppingData(val items: List<ShoppingItemDto>, val suggestions: List<InventoryItemDto>)

class ShoppingViewModel(c: AppContainer) : RemoteVm<ShoppingData>(c) {
    override suspend fun fetch(): ApiResult<ShoppingData> {
        val items = when (val r = c.api.get("api/shopping", ListSerializer(ShoppingItemDto.serializer()))) {
            is ApiResult.Ok -> r.value
            is ApiResult.HttpError -> return r
            is ApiResult.NetworkError -> return r
        }
        val sugg = (c.api.get("api/shopping/suggestions", ListSerializer(InventoryItemDto.serializer())) as? ApiResult.Ok)?.value
        return ApiResult.Ok(ShoppingData(items, sugg.orEmpty()))
    }

    init {
        refresh()
    }

    fun addText(name: String) = act(null) {
        c.api.post(
            "api/shopping",
            buildJsonObject {
                put("name", JsonPrimitive(name.trim()))
                put("quantity", JsonPrimitive(1))
            },
            ShoppingItemDto.serializer(),
        )
    }

    fun addProduct(productId: String) = act(R.string.added_to_shopping) {
        c.api.post(
            "api/shopping",
            buildJsonObject {
                put("product_id", JsonPrimitive(productId))
                put("quantity", JsonPrimitive(1))
            },
            ShoppingItemDto.serializer(),
        )
    }

    // Ticking is last-write-wins (no If-Match); other edits keep optimistic concurrency.
    fun toggle(i: ShoppingItemDto) = act(null) {
        c.api.patch("api/shopping/${i.id}", buildJsonObject { put("checked", JsonPrimitive(!i.checked)) }, ShoppingItemDto.serializer())
    }

    fun setQuantity(i: ShoppingItemDto, q: Double) = act(null) {
        c.api.patch(
            "api/shopping/${i.id}",
            buildJsonObject { put("quantity", JsonPrimitive(q)) },
            ShoppingItemDto.serializer(),
            ifMatch = i.version,
        )
    }

    fun delete(i: ShoppingItemDto) = act(null) { c.api.call("DELETE", "api/shopping/${i.id}") }

    fun clearChecked() = act(null) { c.api.call("POST", "api/shopping/clear-checked") }

    /** "Put the shopping away": ticked items linked to a product go into stock (offline queue), then off the list. */
    fun putAway(items: List<ShoppingItemDto>) {
        viewModelScope.launch(Dispatchers.IO) {
            var n = 0
            items.filter { it.checked && it.productId != null }.forEach { i ->
                if (c.scanRepository.enqueueOp("add", i.productId!!, i.quantity) != null) n++
            }
            c.requestSync()
            message(R.string.put_away_done, n.toString())
            clearChecked()
        }
    }
}

@Composable
fun ShoppingScreen(container: AppContainer, snackbar: SnackbarHostState) {
    val vm: ShoppingViewModel = viewModel(factory = viewModelFactory { initializer { ShoppingViewModel(container) } })
    val load by vm.state.collectAsStateWithLifecycle()
    CollectMessages(vm.messages, snackbar)
    LaunchedEffect(Unit) { vm.refresh() }
    var text by remember { mutableStateOf("") }
    var confirmPutAway by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize()) {
        ScreenHeader(stringResource(R.string.nav_shopping)) {
            IconButton(onClick = { vm.refresh(spinner = true) }) {
                Icon(Icons.Filled.Refresh, contentDescription = stringResource(R.string.refresh))
            }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                singleLine = true,
                label = { Text(stringResource(R.string.shopping_add_hint)) },
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = {
                    if (text.isNotBlank()) vm.addText(text)
                    text = ""
                }),
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = {
                if (text.isNotBlank()) vm.addText(text)
                text = ""
            }) { Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.add)) }
        }
        LoadBox(load, onRetry = { vm.refresh(spinner = true) }) { data ->
            val open = data.items.filter { !it.checked }
            val done = data.items.filter { it.checked }
            LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
                if (data.suggestions.isNotEmpty()) {
                    item {
                        Text(
                            stringResource(R.string.shopping_suggestions),
                            style = MaterialTheme.typography.titleSmall,
                            modifier = Modifier.padding(top = 12.dp),
                        )
                    }
                    items(data.suggestions.take(8), key = { "s" + it.product.id }) { s ->
                        ListRow(
                            title = s.product.name,
                            subtitle = stringResource(R.string.in_stock_qty, QuantityMath.format(s.totalQuantity)),
                            onClick = { vm.addProduct(s.product.id) },
                        ) { Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.add)) }
                    }
                }
                if (data.items.isEmpty()) item { EmptyText(stringResource(R.string.shopping_empty)) }
                // grouped by shop when any item has one, open items first
                open.groupBy { it.store.orEmpty() }.toSortedMap(compareBy<String> { it.isEmpty() }.thenBy { it }).forEach { (store, list) ->
                    item(key = "h$store") {
                        Text(
                            store.ifEmpty { stringResource(R.string.shopping_any_store) },
                            style = MaterialTheme.typography.titleSmall,
                            modifier = Modifier.padding(top = 12.dp),
                        )
                    }
                    items(list, key = { it.id }) { i -> ShoppingRow(i, vm) }
                }
                if (done.isNotEmpty()) {
                    item {
                        Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = { confirmPutAway = true }) {
                                Text(stringResource(R.string.put_away, done.size.toString()))
                            }
                            OutlinedButton(onClick = vm::clearChecked) { Text(stringResource(R.string.clear_checked)) }
                        }
                    }
                    items(done, key = { it.id }) { i -> ShoppingRow(i, vm) }
                }
            }
            if (confirmPutAway) {
                AlertDialog(
                    onDismissRequest = { confirmPutAway = false },
                    title = { Text(stringResource(R.string.put_away_title)) },
                    text = {
                        Column {
                            Text(stringResource(R.string.put_away_hint))
                            done.forEach { i ->
                                Text(
                                    "• ${QuantityMath.format(i.quantity)} × ${i.name}" +
                                        if (i.productId == null) " (" + stringResource(R.string.not_linked) + ")" else "",
                                )
                            }
                        }
                    },
                    confirmButton = {
                        TextButton(onClick = {
                            confirmPutAway = false
                            vm.putAway(done)
                        }) { Text(stringResource(R.string.put_away_confirm)) }
                    },
                    dismissButton = { TextButton(onClick = { confirmPutAway = false }) { Text(stringResource(R.string.cancel)) } },
                )
            }
        }
    }
}

@Composable
private fun ShoppingRow(i: ShoppingItemDto, vm: ShoppingViewModel) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked = i.checked, onCheckedChange = { vm.toggle(i) })
        Column(Modifier.weight(1f)) {
            Text(
                i.name,
                fontWeight = FontWeight.SemiBold,
                textDecoration = if (i.checked) TextDecoration.LineThrough else null,
            )
            i.note?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
        }
        TextButton(onClick = { if (i.quantity > 1) vm.setQuantity(i, i.quantity - 1) }) { Text("−") }
        Text(QuantityMath.format(i.quantity), fontWeight = FontWeight.Bold)
        TextButton(onClick = { vm.setQuantity(i, i.quantity + 1) }) { Text("+") }
        IconButton(onClick = { vm.delete(i) }) {
            Icon(Icons.Filled.Delete, contentDescription = stringResource(R.string.delete))
        }
    }
    HorizontalDivider()
}
