package dk.pantrynanny.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.Checkbox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.MealDto
import dk.pantrynanny.app.data.remote.ShoppingFromDto
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.time.DayOfWeek
import java.time.LocalDate

class PlanViewModel(c: AppContainer) : RemoteVm<List<MealDto>>(c) {
    var start: LocalDate = LocalDate.now().with(DayOfWeek.MONDAY)
        private set

    override suspend fun fetch(): ApiResult<List<MealDto>> =
        c.api.get("api/meal-plan", ListSerializer(MealDto.serializer()), mapOf("start" to start.toString(), "days" to "7"))

    init {
        refresh()
    }

    fun week(delta: Long) {
        start = start.plusWeeks(delta)
        refresh(spinner = true)
    }

    fun toggle(m: MealDto) = act(null) {
        c.api.patch("api/meal-plan/${m.id}", buildJsonObject { put("cooked", JsonPrimitive(m.cookedAt == null)) }, MealDto.serializer())
    }

    fun delete(m: MealDto) = act(null) { c.api.call("DELETE", "api/meal-plan/${m.id}") }

    fun addNote(day: String, slot: String, title: String) = act(R.string.planned) {
        c.api.post(
            "api/meal-plan",
            buildJsonObject {
                put("day", JsonPrimitive(day))
                put("slot", JsonPrimitive(slot))
                put("title", JsonPrimitive(title))
            },
            MealDto.serializer(),
        )
    }

    fun shopWeek() = act(R.string.week_shopped) {
        c.api.post(
            "api/meal-plan/shopping",
            buildJsonObject {
                put("start", JsonPrimitive(start.toString()))
                put("days", JsonPrimitive(7))
            },
            ShoppingFromDto.serializer(),
        )
    }
}

/** Week planner. Planning never changes stock; "Lav den" on the recipe does, after confirming. */
@Composable
fun PlanScreen(
    container: AppContainer,
    snackbar: SnackbarHostState,
    onRecipes: () -> Unit,
    onOpenRecipe: (MealDto) -> Unit,
) {
    val vm: PlanViewModel = viewModel(factory = viewModelFactory { initializer { PlanViewModel(container) } })
    val load by vm.state.collectAsStateWithLifecycle()
    CollectMessages(vm.messages, snackbar)
    LaunchedEffect(Unit) { vm.refresh() }
    var addFor by remember { mutableStateOf<LocalDate?>(null) }
    Column(Modifier.fillMaxSize()) {
        ScreenHeader(stringResource(R.string.tab_food), subtitle = stringResource(R.string.plan_subtitle))
        FoodTabs(onRecipes = false, onSelectRecipes = onRecipes, onSelectPlan = {})
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { vm.week(-1) }) { Text("‹") }
            Text(
                shortDate(vm.start.toString()) + " – " + shortDate(vm.start.plusDays(6).toString()),
                modifier = Modifier.weight(1f),
                fontWeight = FontWeight.SemiBold,
            )
            TextButton(onClick = { vm.week(1) }) { Text("›") }
            OutlinedButton(onClick = vm::shopWeek) { Text(stringResource(R.string.shop_week)) }
        }
        LoadBox(load, onRetry = { vm.refresh(spinner = true) }) { meals ->
            val days = (0L..6L).map { vm.start.plusDays(it) }
            LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(days, key = { it.toString() }) { d ->
                    val today = d == LocalDate.now()
                    SectionCard {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                dayLabel(d),
                                fontWeight = FontWeight.SemiBold,
                                color = if (today) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                                modifier = Modifier.weight(1f),
                            )
                            IconButton(onClick = { addFor = d }) { Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.add)) }
                        }
                        val list = meals.filter { it.day == d.toString() }
                        if (list.isEmpty()) Text(stringResource(R.string.plan_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
                        list.forEach { m ->
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Checkbox(checked = m.cookedAt != null, onCheckedChange = { vm.toggle(m) })
                                Column(Modifier.weight(1f)) {
                                    Text(slotLabel(m.slot), style = MaterialTheme.typography.labelSmall)
                                    Text(
                                        m.recipeTitle ?: m.title ?: "",
                                        fontWeight = FontWeight.SemiBold,
                                        textDecoration = if (m.cookedAt != null) TextDecoration.LineThrough else null,
                                        color = if (m.recipeId != null) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface,
                                    )
                                }
                                if (m.recipeId != null && m.cookedAt == null) {
                                    TextButton(onClick = { onOpenRecipe(m) }) { Text(stringResource(R.string.open)) }
                                }
                                m.missing?.takeIf { it > 0 && m.cookedAt == null }?.let {
                                    Pill(stringResource(R.string.missing_n, it.toString()), WarnColor)
                                }
                                IconButton(onClick = { vm.delete(m) }) {
                                    Icon(Icons.Filled.Delete, contentDescription = stringResource(R.string.delete))
                                }
                            }
                        }
                    }
                }
                item { Text(stringResource(R.string.plan_no_deduction), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(vertical = 12.dp)) }
            }
        }
    }
    addFor?.let { d ->
        NoteMealDialog(d, onDismiss = { addFor = null }, onSave = { slot, title ->
            addFor = null
            vm.addNote(d.toString(), slot, title)
        })
    }
}

/** Add a free-text meal ("Rester", "Takeaway"); recipes are planned from the recipe screen. */
@Composable
private fun NoteMealDialog(day: LocalDate, onDismiss: () -> Unit, onSave: (String, String) -> Unit) {
    var title by remember { mutableStateOf("") }
    var slot by remember { mutableStateOf("dinner") }
    androidx.compose.material3.AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(dayLabel(day)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(stringResource(R.string.plan_add_hint), style = MaterialTheme.typography.bodySmall)
                androidx.compose.material3.OutlinedTextField(
                    value = title, onValueChange = { title = it }, singleLine = true,
                    label = { Text(stringResource(R.string.plan_what)) },
                )
                listOf("breakfast", "lunch", "dinner", "snack").forEach { s ->
                    androidx.compose.material3.FilterChip(selected = slot == s, onClick = { slot = s }, label = { Text(slotLabel(s)) })
                }
            }
        },
        confirmButton = { TextButton(enabled = title.isNotBlank(), onClick = { onSave(slot, title.trim()) }) { Text(stringResource(R.string.save)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}
