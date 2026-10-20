package dk.pantrynanny.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.TransactionDto
import dk.pantrynanny.app.domain.QuantityMath
import kotlinx.serialization.builtins.ListSerializer

class ActivityViewModel(c: AppContainer) : RemoteVm<List<TransactionDto>>(c) {
    override suspend fun fetch(): ApiResult<List<TransactionDto>> =
        c.api.get("api/activity", ListSerializer(TransactionDto.serializer()), mapOf("limit" to "100"))

    init {
        refresh()
    }
}

/** Who changed what, newest first. */
@Composable
fun ActivityScreen(container: AppContainer, snackbar: SnackbarHostState, onBack: () -> Unit, onOpenProduct: (String) -> Unit) {
    val vm: ActivityViewModel = viewModel(factory = viewModelFactory { initializer { ActivityViewModel(container) } })
    val load by vm.state.collectAsStateWithLifecycle()
    CollectMessages(vm.messages, snackbar)
    Column(Modifier.fillMaxSize()) {
        ScreenHeader(stringResource(R.string.nav_activity), onBack = onBack)
        LoadBox(load, onRetry = { vm.refresh(spinner = true) }) { rows ->
            if (rows.isEmpty()) EmptyText(stringResource(R.string.nothing_here))
            LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
                items(rows, key = { it.id }) { t ->
                    val who = t.userName ?: t.deviceName ?: ""
                    val time = t.occurredAt.take(16).replace('T', ' ')
                    ListRow(
                        title = t.product?.name ?: "",
                        subtitle = listOf(time, txnLabel(t.type), who).filter { it.isNotBlank() }.joinToString(" · ") +
                            if (t.undone) " · " + stringResource(R.string.undone) else "",
                        imageUrl = t.product?.imageUrl,
                        showImage = true,
                        onClick = { t.product?.id?.let(onOpenProduct) },
                    ) {
                        Text(
                            (if (t.quantityDelta > 0) "+" else "") + QuantityMath.format(t.quantityDelta),
                            fontWeight = FontWeight.Bold,
                            color = when {
                                t.undone -> MaterialTheme.colorScheme.onSurfaceVariant
                                t.quantityDelta > 0 -> AddColor
                                t.quantityDelta < 0 -> RemoveColor
                                else -> MaterialTheme.colorScheme.onSurface
                            },
                        )
                    }
                    HorizontalDivider()
                }
            }
        }
    }
}
