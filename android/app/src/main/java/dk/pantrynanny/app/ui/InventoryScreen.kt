package dk.pantrynanny.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
import dk.pantrynanny.app.data.local.LocationEntity
import dk.pantrynanny.app.data.local.ProductWithQty
import dk.pantrynanny.app.domain.QuantityMath
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.stateIn

data class InventoryUiState(
    val query: String = "",
    val unknownOnly: Boolean = false,
    val locationId: String? = null,
    val locations: List<LocationEntity> = emptyList(),
    val items: List<ProductWithQty> = emptyList(),
)

@OptIn(ExperimentalCoroutinesApi::class)
class InventoryViewModel(private val c: AppContainer) : ViewModel() {
    private val query = MutableStateFlow("")
    private val unknownOnly = MutableStateFlow(false)
    private val locationId = MutableStateFlow<String?>(null)

    private val filters = combine(query, unknownOnly, locationId) { q, u, l -> Triple(q, u, l) }

    private val items = filters.flatMapLatest { (q, u, l) ->
        c.db.productDao().observeProducts(q.trim().lowercase(), if (u) 1 else 0, l)
    }

    val state: StateFlow<InventoryUiState> = combine(
        filters, c.db.locationDao().observeAll(), items,
    ) { (q, u, l), locations, all ->
        // "På lager" hides empty products unless the user is searching.
        val shown = if (u || q.isNotBlank()) all else all.filter { it.displayQuantity > QuantityMath.EPSILON }
        InventoryUiState(q, u, l, locations, shown)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), InventoryUiState())

    fun setQuery(q: String) {
        query.value = q
    }

    fun setUnknownOnly(on: Boolean) {
        unknownOnly.value = on
    }

    fun setLocation(id: String?) {
        locationId.value = if (locationId.value == id) null else id
    }
}

@Composable
fun InventoryScreen(container: AppContainer, onOpenProduct: (String) -> Unit) {
    val vm: InventoryViewModel = viewModel(factory = viewModelFactory { initializer { InventoryViewModel(container) } })
    val ui by vm.state.collectAsStateWithLifecycle()

    Column(Modifier.fillMaxSize().padding(horizontal = 12.dp)) {
        Text(
            stringResource(R.string.nav_inventory),
            style = MaterialTheme.typography.headlineSmall,
            modifier = Modifier.padding(top = 8.dp),
        )
        OutlinedTextField(
            value = ui.query,
            onValueChange = vm::setQuery,
            label = { Text(stringResource(R.string.search_hint)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(
                selected = !ui.unknownOnly,
                onClick = { vm.setUnknownOnly(false) },
                label = { Text(stringResource(R.string.tab_in_stock)) },
            )
            FilterChip(
                selected = ui.unknownOnly,
                onClick = { vm.setUnknownOnly(true) },
                label = { Text(stringResource(R.string.tab_unknown)) },
            )
        }
        if (ui.locations.isNotEmpty() && !ui.unknownOnly) {
            LazyRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.padding(vertical = 6.dp),
            ) {
                items(ui.locations, key = { it.id }) { loc ->
                    FilterChip(
                        selected = ui.locationId == loc.id,
                        onClick = { vm.setLocation(loc.id) },
                        label = { Text(loc.name) },
                    )
                }
            }
        }
        if (ui.items.isEmpty()) {
            Text(
                stringResource(if (ui.unknownOnly) R.string.empty_unknown else R.string.empty_inventory),
                modifier = Modifier.padding(16.dp),
            )
        }
        LazyColumn(Modifier.fillMaxSize()) {
            items(ui.items, key = { it.product.id }) { item ->
                ProductRow(item, onClick = { onOpenProduct(item.product.id) })
                HorizontalDivider()
            }
        }
    }
}

@Composable
private fun ProductRow(item: ProductWithQty, onClick: () -> Unit) {
    val p = item.product
    val low = QuantityMath.isLowStock(item.displayQuantity, p.minStock)
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        ProductImage(p.imageUrl, null, Modifier.size(48.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(p.name, fontWeight = FontWeight.Bold, maxLines = 2)
            val sub = listOfNotNull(p.brand?.takeIf { it.isNotBlank() }, if (p.status != "known") stringResource(R.string.status_unknown_badge) else null)
            if (sub.isNotEmpty()) Text(sub.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
            if (low) Text(stringResource(R.string.low_stock), color = WarnColor, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.width(8.dp))
        Text(
            stringResource(R.string.quantity_with_unit, QuantityMath.format(maxOf(item.displayQuantity, 0.0)), unitLabel(p.stockUnit)),
            fontWeight = FontWeight.Bold,
        )
    }
}
