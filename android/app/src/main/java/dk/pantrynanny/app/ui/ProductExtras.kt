package dk.pantrynanny.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.local.BatchEntity
import dk.pantrynanny.app.data.local.LocationEntity
import dk.pantrynanny.app.data.remote.InventoryItemDto
import dk.pantrynanny.app.data.remote.RunOutDto
import dk.pantrynanny.app.domain.QuantityMath
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.doubleOrNull
import java.time.LocalDate

/** Parse "1,5" / "2" -> number, or null. */
fun parseQty(text: String): Double? = text.trim().replace(',', '.').toDoubleOrNull()

/** Product actions: take out N, count, move, shopping list, favourite. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ProductActions(
    favorite: Boolean?,
    onTakeOut: () -> Unit,
    onCount: () -> Unit,
    onMove: () -> Unit,
    onShopping: () -> Unit,
    onFavorite: () -> Unit,
) {
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        AssistChip(onClick = onTakeOut, label = { Text(stringResource(R.string.action_take_out)) })
        AssistChip(onClick = onCount, label = { Text(stringResource(R.string.action_count)) })
        AssistChip(onClick = onMove, label = { Text(stringResource(R.string.action_move)) })
        AssistChip(onClick = onShopping, label = { Text(stringResource(R.string.action_to_shopping)) })
        if (favorite != null) {
            AssistChip(
                onClick = onFavorite,
                label = { Text(stringResource(if (favorite) R.string.action_unfavorite else R.string.action_favorite)) },
            )
        }
    }
}

/** Batches per location with expiry; tapping one opens the expiry dialog. */
@Composable
fun BatchList(batches: List<BatchEntity>, locations: List<LocationEntity>, onEditExpiry: (BatchEntity) -> Unit) {
    Text(stringResource(R.string.batches), fontWeight = FontWeight.Bold)
    val live = batches.filter { it.quantity > QuantityMath.EPSILON }
    if (live.isEmpty()) Text(stringResource(R.string.no_batches))
    live.forEach { b ->
        val loc = locations.firstOrNull { it.id == b.locationId }?.name ?: "-"
        val days = daysUntil(b.expiresAt)
        Row(
            Modifier.fillMaxWidth().clickable { onEditExpiry(b) }.padding(vertical = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(loc, modifier = Modifier.weight(1f))
            Text(
                when {
                    b.expiresAt == null -> stringResource(R.string.expiry_set)
                    days != null && days < 0 -> stringResource(R.string.expired_on, shortDate(b.expiresAt))
                    else -> stringResource(R.string.expires, shortDate(b.expiresAt))
                },
                color = when {
                    days != null && days < 0 -> MaterialTheme.colorScheme.error
                    days != null && days <= 3 -> WarnColor
                    else -> MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
            Text(QuantityMath.format(b.quantity), fontWeight = FontWeight.Bold)
        }
        HorizontalDivider()
    }
}

/** Nutrition, ingredients, allergens and the rest of what the web shows, from the server. */
@Composable
fun ProductDetailsCard(item: InventoryItemDto, runOut: RunOutDto?) {
    val p = item.product
    SectionCard(stringResource(R.string.details)) {
        runOut?.let {
            Text(stringResource(R.string.runout_line, Math.round(it.daysLeft).coerceAtLeast(1L).toString()), color = WarnColor)
        }
        if (p.packageSize != null) {
            Text(stringResource(R.string.package_size, QuantityMath.format(p.packageSize), p.packageUnit ?: ""))
        }
        p.description?.takeIf { it.isNotBlank() }?.let { Text(it) }
        val nutrition = p.nutrition?.entries?.filter { it.key != "per" }.orEmpty()
        if (nutrition.isNotEmpty()) {
            Text(stringResource(R.string.nutrition_per_100), fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 6.dp))
            nutrition.forEach { (k, v) ->
                val num = (v as? JsonPrimitive)?.doubleOrNull
                Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                    Text(nutrientLabel(k), modifier = Modifier.weight(1f))
                    Text(
                        if (num != null) QuantityMath.format(num) + (if (k == "energy_kcal") " kcal" else " g") else v.toString(),
                        fontWeight = FontWeight.SemiBold,
                    )
                }
                HorizontalDivider()
            }
        }
        p.ingredients?.takeIf { it.isNotBlank() }?.let {
            Text(stringResource(R.string.ingredients), fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 6.dp))
            Text(it, style = MaterialTheme.typography.bodySmall)
        }
        if (p.allergens.isNotEmpty()) {
            Text(stringResource(R.string.allergens), fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 6.dp))
            Text(p.allergens.joinToString(", "))
        }
        if (p.countries.isNotEmpty()) {
            Text(stringResource(R.string.countries, p.countries.joinToString(", ")), style = MaterialTheme.typography.bodySmall)
        }
        val attribution = p.sourceAttribution ?: if (p.source == "openfoodfacts") "Open Food Facts – ODbL" else null
        attribution?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        if (nutrition.isEmpty() && p.ingredients.isNullOrBlank() && p.allergens.isEmpty() && p.description.isNullOrBlank()) {
            Text(stringResource(R.string.no_details), color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
    if (item.transactions.isNotEmpty()) {
        SectionCard(stringResource(R.string.history)) {
            item.transactions.take(12).forEach { t ->
                Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                    Text(
                        txnLabel(t.type) + (t.deviceName?.let { " · $it" } ?: ""),
                        modifier = Modifier.weight(1f),
                        style = MaterialTheme.typography.bodySmall,
                    )
                    Text(shortDate(t.occurredAt), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(end = 8.dp))
                    Text(
                        (if (t.quantityDelta > 0) "+" else "") + QuantityMath.format(t.quantityDelta),
                        fontWeight = FontWeight.Bold,
                        color = if (t.undone) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                    )
                }
            }
        }
    }
}

@Composable
fun nutrientLabel(key: String): String = when (key) {
    "energy_kcal" -> stringResource(R.string.nutr_energy)
    "fat" -> stringResource(R.string.nutr_fat)
    "saturated_fat" -> stringResource(R.string.nutr_saturated_fat)
    "carbohydrates" -> stringResource(R.string.nutr_carbohydrates)
    "sugars" -> stringResource(R.string.nutr_sugars)
    "fiber" -> stringResource(R.string.nutr_fiber)
    "proteins" -> stringResource(R.string.nutr_proteins)
    "salt" -> stringResource(R.string.nutr_salt)
    else -> key
}

@Composable
fun txnLabel(type: String): String = when (type) {
    "add" -> stringResource(R.string.txn_add)
    "remove" -> stringResource(R.string.txn_remove)
    "adjust" -> stringResource(R.string.txn_adjust)
    "move" -> stringResource(R.string.txn_move)
    "undo" -> stringResource(R.string.txn_undo)
    else -> type
}

/** Ask for a number (take out N / count). */
@Composable
fun QuantityDialog(title: String, initial: String, confirm: String, onDismiss: () -> Unit, onConfirm: (Double) -> Unit) {
    var text by remember { mutableStateOf(initial) }
    val value = parseQty(text)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            )
        },
        confirmButton = {
            TextButton(enabled = value != null && value >= 0, onClick = { value?.let(onConfirm) }) { Text(confirm) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

/** Pick a location (move). */
@Composable
fun LocationDialog(locations: List<LocationEntity>, onDismiss: () -> Unit, onPick: (LocationEntity) -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.move_to)) },
        text = {
            Column {
                locations.forEach { l ->
                    Text(l.name, modifier = Modifier.fillMaxWidth().clickable { onPick(l) }.padding(vertical = 12.dp))
                }
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

/** Expiry date: quick +N days, a typed date (YYYY-MM-DD) or none. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ExpiryDialog(current: String?, onDismiss: () -> Unit, onSave: (String?) -> Unit) {
    var text by remember { mutableStateOf(current ?: "") }
    val valid = text.isBlank() || runCatching { LocalDate.parse(text.trim()) }.isSuccess
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.expiry_title)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf(1L, 3L, 7L, 14L, 30L).forEach { n ->
                        AssistChip(
                            onClick = { text = LocalDate.now().plusDays(n).toString() },
                            label = { Text("+$n") },
                        )
                    }
                }
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    singleLine = true,
                    label = { Text(stringResource(R.string.expiry_date_hint)) },
                    isError = !valid,
                )
            }
        },
        confirmButton = {
            TextButton(enabled = valid, onClick = { onSave(text.trim().ifEmpty { null }) }) { Text(stringResource(R.string.save)) }
        },
        dismissButton = {
            Row {
                TextButton(onClick = { onSave(null) }) { Text(stringResource(R.string.expiry_none)) }
                TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) }
            }
        },
    )
}
