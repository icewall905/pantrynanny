package dk.pantrynanny.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.DashboardDto
import dk.pantrynanny.app.data.remote.InventoryItemDto
import dk.pantrynanny.app.data.remote.RunOutDto
import dk.pantrynanny.app.domain.QuantityMath
import kotlinx.serialization.builtins.ListSerializer

data class OverviewData(val dashboard: DashboardDto, val runOut: List<RunOutDto>)

class OverviewViewModel(c: AppContainer) : RemoteVm<OverviewData>(c) {
    override suspend fun fetch(): ApiResult<OverviewData> {
        val d = when (val r = c.api.get("api/dashboard", DashboardDto.serializer())) {
            is ApiResult.Ok -> r.value
            is ApiResult.HttpError -> return r
            is ApiResult.NetworkError -> return r
        }
        val run = (c.api.get("api/stats/runout", ListSerializer(RunOutDto.serializer()), mapOf("days" to "10")) as? ApiResult.Ok)?.value
        return ApiResult.Ok(OverviewData(d, run.orEmpty()))
    }

    init {
        refresh()
    }
}

/** Home: the numbers, what to use first, what is running low, and unnamed products. */
@Composable
fun OverviewScreen(
    container: AppContainer,
    snackbar: SnackbarHostState,
    onBack: () -> Unit,
    onOpenProduct: (String) -> Unit,
    onOpenUnknown: () -> Unit,
    onOpenShopping: () -> Unit,
) {
    val vm: OverviewViewModel = viewModel(factory = viewModelFactory { initializer { OverviewViewModel(container) } })
    val load by vm.state.collectAsStateWithLifecycle()
    CollectMessages(vm.messages, snackbar)
    LaunchedEffect(Unit) { vm.refresh() }
    Column(Modifier.fillMaxSize()) {
        ScreenHeader(stringResource(R.string.nav_overview), onBack = onBack)
        LoadBox(load, onRetry = { vm.refresh(spinner = true) }) { data ->
            val d = data.dashboard
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    StatTile(d.totals.productsInStock.toString(), stringResource(R.string.stat_in_stock), Modifier.weight(1f))
                    StatTile((d.expired.size + d.expiringSoon.size).toString(), stringResource(R.string.stat_expiring), Modifier.weight(1f))
                    StatTile(d.shoppingOpenCount.toString(), stringResource(R.string.stat_shopping), Modifier.weight(1f), onClick = onOpenShopping)
                }
                if (d.unknownCount > 0) {
                    SectionCard(onClick = onOpenUnknown) {
                        Text(stringResource(R.string.unknown_nudge, d.unknownCount.toString()), color = WarnColor, fontWeight = FontWeight.SemiBold)
                    }
                }
                ItemSection(stringResource(R.string.use_first), d.expired + d.expiringSoon, onOpenProduct, expiry = true)
                if (data.runOut.isNotEmpty()) {
                    SectionCard(stringResource(R.string.runs_out_soon)) {
                        data.runOut.take(6).forEach { r ->
                            ListRow(
                                title = r.name,
                                subtitle = stringResource(R.string.in_stock_qty, QuantityMath.format(r.totalQuantity)),
                                imageUrl = r.imageUrl,
                                showImage = true,
                                onClick = { onOpenProduct(r.productId) },
                            ) { Pill(stringResource(R.string.days_approx, Math.round(r.daysLeft).coerceAtLeast(1L).toString()), WarnColor) }
                        }
                    }
                }
                ItemSection(stringResource(R.string.low_stock), d.lowStock, onOpenProduct, expiry = false)
            }
        }
    }
}

@Composable
private fun StatTile(value: String, label: String, modifier: Modifier, onClick: (() -> Unit)? = null) {
    SectionCard(modifier = modifier, onClick = onClick) {
        Text(value, fontSize = 28.sp, fontWeight = FontWeight.Bold)
        Text(label, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun ItemSection(title: String, items: List<InventoryItemDto>, onOpen: (String) -> Unit, expiry: Boolean) {
    SectionCard(title) {
        if (items.isEmpty()) {
            Text(stringResource(R.string.nothing_here), color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        items.take(10).forEach { item ->
            val days = daysUntil(item.nextExpiry)
            ListRow(
                title = item.product.name,
                subtitle = stringResource(R.string.in_stock_qty, QuantityMath.format(item.totalQuantity)),
                imageUrl = item.product.imageUrl,
                showImage = true,
                onClick = { onOpen(item.product.id) },
            ) {
                if (expiry && item.nextExpiry != null) {
                    Pill(
                        if (days != null && days < 0) stringResource(R.string.expired) else shortDate(item.nextExpiry),
                        if (days != null && days < 0) MaterialTheme.colorScheme.error else WarnColor,
                    )
                }
            }
        }
    }
}
