package dk.pantrynanny.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.AvailabilityDto
import dk.pantrynanny.app.data.remote.MealDto
import dk.pantrynanny.app.data.remote.RecipeDraftDto
import dk.pantrynanny.app.data.remote.RecipeDto
import dk.pantrynanny.app.data.remote.RecipeSummaryDto
import dk.pantrynanny.app.data.remote.ShoppingFromDto
import dk.pantrynanny.app.domain.QuantityMath
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import java.time.LocalDate

/** "Opskrifter | Madplan": the two halves of the food tab. */
@Composable
fun FoodTabs(onRecipes: Boolean, onSelectRecipes: () -> Unit, onSelectPlan: () -> Unit) {
    Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        FilterChip(selected = onRecipes, onClick = onSelectRecipes, label = { Text(stringResource(R.string.nav_recipes)) })
        FilterChip(selected = !onRecipes, onClick = onSelectPlan, label = { Text(stringResource(R.string.nav_plan)) })
    }
}

class RecipesViewModel(c: AppContainer) : RemoteVm<List<RecipeSummaryDto>>(c) {
    var maxMinutes: Int? = null
        private set

    override suspend fun fetch(): ApiResult<List<RecipeSummaryDto>> =
        c.api.get(
            "api/recipes/suggest",
            ListSerializer(RecipeSummaryDto.serializer()),
            maxMinutes?.let { mapOf("max_minutes" to it.toString()) } ?: emptyMap(),
        )

    fun setMax(m: Int?) {
        maxMinutes = m
        refresh(spinner = true)
    }

    init {
        refresh()
    }
}

/** "What can we cook?": saved recipes ranked by what is at home. */
@Composable
fun RecipesScreen(
    container: AppContainer,
    snackbar: SnackbarHostState,
    onOpen: (String) -> Unit,
    onNew: () -> Unit,
    onPlan: () -> Unit,
) {
    val vm: RecipesViewModel = viewModel(factory = viewModelFactory { initializer { RecipesViewModel(container) } })
    val load by vm.state.collectAsStateWithLifecycle()
    CollectMessages(vm.messages, snackbar)
    LaunchedEffect(Unit) { vm.refresh() }
    Column(Modifier.fillMaxSize()) {
        ScreenHeader(stringResource(R.string.tab_food), subtitle = stringResource(R.string.recipes_subtitle)) {
            IconButton(onClick = onNew) { Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.recipe_new)) }
        }
        FoodTabs(onRecipes = true, onSelectRecipes = {}, onSelectPlan = onPlan)
        Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf<Int?>(null, 30, 60).forEach { m ->
                FilterChip(
                    selected = vm.maxMinutes == m,
                    onClick = { vm.setMax(m) },
                    label = { Text(if (m == null) stringResource(R.string.any_time) else stringResource(R.string.max_minutes, m.toString())) },
                )
            }
        }
        LoadBox(load, onRetry = { vm.refresh(spinner = true) }) { list ->
            if (list.isEmpty()) EmptyText(stringResource(R.string.recipes_empty))
            LazyColumn(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(list, key = { it.recipe.id }) { s -> RecipeCard(s, onClick = { onOpen(s.recipe.id) }) }
            }
        }
    }
}

@Composable
private fun RecipeCard(s: RecipeSummaryDto, onClick: () -> Unit) {
    val a = s.availability
    SectionCard(onClick = onClick) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(s.recipe.title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            if (a.missing == 0) Pill(stringResource(R.string.all_home), AddColor)
            else Pill(stringResource(R.string.missing_n, a.missing.toString()), WarnColor)
        }
        val meta = listOfNotNull(
            s.recipe.totalMinutes.takeIf { it > 0 }?.let { stringResource(R.string.minutes, it.toString()) },
            stringResource(R.string.servings, s.recipe.servings.toString()),
        )
        Text(meta.joinToString(" · "), style = MaterialTheme.typography.bodySmall)
        LinearProgressIndicator(progress = { a.coverage.toFloat() }, modifier = Modifier.fillMaxWidth())
        if (a.usesExpiring.isNotEmpty()) {
            Text(stringResource(R.string.uses_up, a.usesExpiring.joinToString(", ")), color = WarnColor, style = MaterialTheme.typography.bodySmall)
        }
    }
}

// ---- detail ------------------------------------------------------------------------------------

data class RecipeData(val recipe: RecipeDto, val availability: AvailabilityDto)

class RecipeDetailViewModel(c: AppContainer, private val id: String, initialServings: Int?) : RemoteVm<RecipeData>(c) {
    var servings: Int? = initialServings
        private set

    /** Op ids of the last "cook", for undo. */
    private val _cooked = MutableStateFlow<List<String>>(emptyList())
    val cooked: StateFlow<List<String>> = _cooked.asStateFlow()

    override suspend fun fetch(): ApiResult<RecipeData> {
        val r = when (val x = c.api.get("api/recipes/$id", RecipeDto.serializer())) {
            is ApiResult.Ok -> x.value
            is ApiResult.HttpError -> return x
            is ApiResult.NetworkError -> return x
        }
        val q = (servings ?: r.servings).toString()
        return when (val a = c.api.get("api/recipes/$id/availability", AvailabilityDto.serializer(), mapOf("servings" to q))) {
            is ApiResult.Ok -> ApiResult.Ok(RecipeData(r, a.value))
            is ApiResult.HttpError -> a
            is ApiResult.NetworkError -> a
        }
    }

    init {
        refresh()
    }

    fun setServings(n: Int) {
        if (n < 1) return
        servings = n
        refresh()
    }

    fun shopMissing() {
        viewModelScope.launch {
            val body = buildJsonObject { servings?.let { put("servings", JsonPrimitive(it)) } }
            when (val r = c.api.post("api/recipes/$id/shopping", body, ShoppingFromDto.serializer())) {
                is ApiResult.Ok -> message(
                    if (r.value.added.isEmpty()) R.string.nothing_to_buy else R.string.added_n_to_shopping,
                    r.value.added.size.toString(),
                )
                is ApiResult.NetworkError -> message(R.string.edit_offline)
                is ApiResult.HttpError -> message(R.string.edit_failed, r.detail ?: "HTTP ${r.code}")
            }
        }
    }

    fun plan(day: String, slot: String) = act(R.string.planned) {
        c.api.post(
            "api/meal-plan",
            buildJsonObject {
                put("day", JsonPrimitive(day))
                put("slot", JsonPrimitive(slot))
                put("recipe_id", JsonPrimitive(id))
                servings?.let { put("servings", JsonPrimitive(it)) }
            },
            MealDto.serializer(),
        )
    }

    fun delete(onDone: () -> Unit) {
        viewModelScope.launch {
            if (c.api.call("DELETE", "api/recipes/$id") is ApiResult.Ok) onDone() else message(R.string.edit_offline)
        }
    }

    /** Take the confirmed amounts out of stock (offline queue, one op per product). */
    fun cook(lines: List<Pair<String, Double>>, mealId: String?) {
        viewModelScope.launch(Dispatchers.IO) {
            val ids = lines.mapNotNull { (pid, q) -> c.scanRepository.enqueueOp("remove", pid, q)?.clientOpId }
            _cooked.value = ids
            c.requestSync()
            if (mealId != null) {
                c.api.patch("api/meal-plan/$mealId", buildJsonObject { put("cooked", JsonPrimitive(true)) }, MealDto.serializer())
            }
            message(R.string.cooked_n, ids.size.toString())
        }
    }

    fun undoCook() {
        val ids = _cooked.value
        _cooked.value = emptyList()
        viewModelScope.launch(Dispatchers.IO) {
            ids.forEach { c.scanRepository.undo(it) }
            c.requestSync()
            message(R.string.cook_undone)
        }
    }
}

@Composable
fun RecipeDetailScreen(
    container: AppContainer,
    id: String,
    servings: Int?,
    mealId: String?,
    snackbar: SnackbarHostState,
    onBack: () -> Unit,
    onEdit: () -> Unit,
) {
    val vm: RecipeDetailViewModel = viewModel(
        key = "recipe-$id",
        factory = viewModelFactory { initializer { RecipeDetailViewModel(container, id, servings) } },
    )
    val load by vm.state.collectAsStateWithLifecycle()
    val cooked by vm.cooked.collectAsStateWithLifecycle()
    CollectMessages(vm.messages, snackbar)
    var cookOpen by remember { mutableStateOf(false) }
    var planOpen by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize()) {
        val title = (load as? Load.Ok)?.value?.recipe?.title ?: ""
        ScreenHeader(title, onBack = onBack)
        LoadBox(load, onRetry = { vm.refresh(spinner = true) }) { data ->
            val r = data.recipe
            val a = data.availability
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                r.description?.takeIf { it.isNotBlank() }?.let { Text(it) }
                Text(
                    listOfNotNull(
                        r.totalMinutes.takeIf { it > 0 }?.let { stringResource(R.string.minutes, it.toString()) },
                        r.sourceName ?: r.sourceUrl,
                    ).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { cookOpen = true }) { Text(stringResource(R.string.cook_this)) }
                    OutlinedButton(onClick = vm::shopMissing, enabled = a.missing > 0) {
                        Text(stringResource(R.string.missing_to_list))
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { planOpen = true }) { Text(stringResource(R.string.plan)) }
                    OutlinedButton(onClick = onEdit) { Text(stringResource(R.string.edit)) }
                    TextButton(onClick = { confirmDelete = true }) { Text(stringResource(R.string.delete)) }
                }
                if (cooked.isNotEmpty()) {
                    OutlinedButton(onClick = vm::undoCook) { Text(stringResource(R.string.undo_cook)) }
                }
                SectionCard(stringResource(R.string.ingredients)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(stringResource(R.string.servings, a.servings.toString()), modifier = Modifier.weight(1f))
                        TextButton(onClick = { vm.setServings(a.servings - 1) }) { Text("−") }
                        TextButton(onClick = { vm.setServings(a.servings + 1) }) { Text("+") }
                    }
                    Text(
                        if (a.missing == 0) stringResource(R.string.all_home)
                        else stringResource(R.string.coverage, a.have.toString(), a.required.toString()),
                        style = MaterialTheme.typography.bodySmall,
                    )
                    a.items.forEach { row ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(row.ingredient.raw)
                                row.product?.let { p ->
                                    Text(
                                        stringResource(R.string.matched_product, p.name, QuantityMath.format(p.totalQuantity)),
                                        style = MaterialTheme.typography.bodySmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                            StatusPill(row.status)
                        }
                        HorizontalDivider()
                    }
                }
                if (r.instructions.isNotEmpty()) {
                    SectionCard(stringResource(R.string.method)) {
                        r.instructions.forEachIndexed { i, step ->
                            Text("${i + 1}. $step", modifier = Modifier.padding(vertical = 4.dp))
                        }
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
            if (cookOpen) {
                CookDialog(a, onDismiss = { cookOpen = false }, onConfirm = { lines ->
                    cookOpen = false
                    vm.cook(lines, mealId)
                })
            }
            if (planOpen) {
                PlanDialog(onDismiss = { planOpen = false }, onSave = { day, slot ->
                    planOpen = false
                    vm.plan(day, slot)
                })
            }
            if (confirmDelete) {
                AlertDialog(
                    onDismissRequest = { confirmDelete = false },
                    title = { Text(stringResource(R.string.recipe_delete_q)) },
                    confirmButton = {
                        TextButton(onClick = {
                            confirmDelete = false
                            vm.delete(onBack)
                        }) { Text(stringResource(R.string.delete)) }
                    },
                    dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text(stringResource(R.string.cancel)) } },
                )
            }
        }
    }
}

@Composable
fun StatusPill(status: String) {
    when (status) {
        "have" -> Pill(stringResource(R.string.st_have), AddColor)
        "low" -> Pill(stringResource(R.string.st_low), WarnColor)
        "missing" -> Pill(stringResource(R.string.st_missing), RemoveColor)
        "staple" -> Pill(stringResource(R.string.st_staple))
        else -> Pill(stringResource(R.string.st_optional))
    }
}

private class CookLine(val productId: String, val name: String, val unit: String, val stock: Double, qty: String, on: Boolean) {
    var qty by mutableStateOf(qty)
    var on by mutableStateOf(on)
}

/** Shows exactly what will be taken out of stock; nothing happens until "Take out". */
@Composable
private fun CookDialog(a: AvailabilityDto, onDismiss: () -> Unit, onConfirm: (List<Pair<String, Double>>) -> Unit) {
    val lines = remember(a) {
        mutableStateListOf<CookLine>().apply {
            a.items.filter { it.product != null && it.product.totalQuantity > 0 && it.status != "staple" }.forEach { row ->
                val p = row.product!!
                val need = row.need?.let { n -> minOf(n, p.totalQuantity) }
                add(CookLine(p.id, p.name, p.stockUnit, p.totalQuantity, need?.let { n -> QuantityMath.format(n) } ?: "", need != null && need > 0))
            }
        }
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.cook_this)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(stringResource(R.string.cook_hint), style = MaterialTheme.typography.bodySmall)
                if (lines.isEmpty()) Text(stringResource(R.string.cook_none))
                lines.forEach { l ->
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = l.on, onCheckedChange = { l.on = it })
                        Text(l.name, modifier = Modifier.weight(1f))
                        OutlinedTextField(
                            value = l.qty,
                            onValueChange = {
                                l.qty = it
                                l.on = it.isNotBlank()
                            },
                            singleLine = true,
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                            modifier = Modifier.fillMaxWidth(0.35f),
                        )
                        Text(" " + unitLabel(l.unit))
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = {
                onConfirm(
                    lines.filter { it.on }.mapNotNull { l ->
                        parseQty(l.qty)?.takeIf { it > 0 }?.let { l.productId to minOf(it, l.stock) }
                    },
                )
            }) { Text(stringResource(R.string.take_out)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

private val SLOTS = listOf("breakfast", "lunch", "dinner", "snack")

@Composable
fun slotLabel(slot: String): String = when (slot) {
    "breakfast" -> stringResource(R.string.slot_breakfast)
    "lunch" -> stringResource(R.string.slot_lunch)
    "snack" -> stringResource(R.string.slot_snack)
    else -> stringResource(R.string.slot_dinner)
}

/** Day (next 14 days) + meal. */
@Composable
fun PlanDialog(onDismiss: () -> Unit, onSave: (String, String) -> Unit, initialDay: LocalDate = LocalDate.now()) {
    var day by remember { mutableStateOf(initialDay) }
    var slot by remember { mutableStateOf("dinner") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.plan)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { day = day.minusDays(1) }) { Text("‹") }
                    Text(dayLabel(day), modifier = Modifier.weight(1f), fontWeight = FontWeight.SemiBold)
                    TextButton(onClick = { day = day.plusDays(1) }) { Text("›") }
                }
                SLOTS.forEach { s ->
                    FilterChip(selected = slot == s, onClick = { slot = s }, label = { Text(slotLabel(s)) })
                }
            }
        },
        confirmButton = { TextButton(onClick = { onSave(day.toString(), slot) }) { Text(stringResource(R.string.save)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

fun dayLabel(d: LocalDate): String =
    d.format(java.time.format.DateTimeFormatter.ofPattern("EEEE d. MMM", java.util.Locale.getDefault()))
        .replaceFirstChar { it.uppercase() }

// ---- editor ------------------------------------------------------------------------------------

class RecipeEditViewModel(c: AppContainer, private val id: String?) : RemoteVm<RecipeDto?>(c) {
    override suspend fun fetch(): ApiResult<RecipeDto?> =
        if (id == null) ApiResult.Ok(null)
        else when (val r = c.api.get("api/recipes/$id", RecipeDto.serializer())) {
            is ApiResult.Ok -> ApiResult.Ok(r.value)
            is ApiResult.HttpError -> r
            is ApiResult.NetworkError -> r
        }

    init {
        refresh()
    }

    private val _draft = MutableStateFlow<RecipeDraftDto?>(null)
    val draft: StateFlow<RecipeDraftDto?> = _draft.asStateFlow()

    fun import(url: String) {
        viewModelScope.launch {
            when (val r = c.api.post("api/recipes/import", buildJsonObject { put("url", JsonPrimitive(url.trim())) }, RecipeDraftDto.serializer())) {
                is ApiResult.Ok -> _draft.value = r.value
                is ApiResult.NetworkError -> message(R.string.edit_offline)
                is ApiResult.HttpError -> message(R.string.edit_failed, r.detail ?: "HTTP ${r.code}")
            }
        }
    }

    fun save(form: RecipeForm, onSaved: (String) -> Unit) {
        val body = buildJsonObject {
            put("title", JsonPrimitive(form.title.trim()))
            put("description", form.description.trim().ifEmpty { null }?.let { JsonPrimitive(it) } ?: JsonNull)
            put("servings", JsonPrimitive(form.servings.toIntOrNull()?.coerceIn(1, 100) ?: 4))
            put("prep_min", form.prep.toIntOrNull()?.let { JsonPrimitive(it) } ?: JsonNull)
            put("cook_min", form.cook.toIntOrNull()?.let { JsonPrimitive(it) } ?: JsonNull)
            put("instructions", JsonArray(form.method.split(Regex("\\n\\s*\\n")).map { it.trim() }.filter { it.isNotEmpty() }.map { JsonPrimitive(it) }))
            put("tags", JsonArray(emptyList<JsonElement>()))
            put("source_url", form.sourceUrl?.let { JsonPrimitive(it) } ?: JsonNull)
            put("source_name", form.sourceName?.let { JsonPrimitive(it) } ?: JsonNull)
            put("image_url", form.imageUrl?.let { JsonPrimitive(it) } ?: JsonNull)
            put(
                "ingredients",
                JsonArray(
                    form.ingredients.lines().map { it.trim() }.filter { it.isNotEmpty() }.take(100).map { line ->
                        buildJsonObject { put("raw", JsonPrimitive(line)) }
                    },
                ),
            )
        }
        viewModelScope.launch {
            val r = if (id == null) {
                c.api.post("api/recipes", body, RecipeDto.serializer())
            } else {
                c.api.put("api/recipes/$id", body, RecipeDto.serializer())
            }
            when (r) {
                is ApiResult.Ok -> {
                    message(R.string.edit_saved)
                    onSaved(r.value.id)
                }
                is ApiResult.NetworkError -> message(R.string.edit_offline)
                is ApiResult.HttpError -> message(R.string.edit_failed, r.detail ?: "HTTP ${r.code}")
            }
        }
    }
}

data class RecipeForm(
    val title: String = "",
    val description: String = "",
    val servings: String = "4",
    val prep: String = "",
    val cook: String = "",
    val ingredients: String = "",
    val method: String = "",
    val sourceUrl: String? = null,
    val sourceName: String? = null,
    val imageUrl: String? = null,
)

private fun RecipeDto.toForm() = RecipeForm(
    title, description.orEmpty(), servings.toString(), prepMin?.toString().orEmpty(), cookMin?.toString().orEmpty(),
    ingredients.joinToString("\n") { it.raw }, instructions.joinToString("\n\n"), sourceUrl, sourceName, imageUrl,
)

private fun RecipeDraftDto.toForm() = RecipeForm(
    title, description.orEmpty(), (servings ?: 4).toString(), prepMin?.toString().orEmpty(), cookMin?.toString().orEmpty(),
    ingredients.joinToString("\n"), instructions.joinToString("\n\n"), sourceUrl, sourceName, imageUrl,
)

@Composable
fun RecipeEditScreen(container: AppContainer, id: String?, snackbar: SnackbarHostState, onBack: () -> Unit, onSaved: (String) -> Unit) {
    val vm: RecipeEditViewModel = viewModel(
        key = "recipe-edit-${id ?: "new"}",
        factory = viewModelFactory { initializer { RecipeEditViewModel(container, id) } },
    )
    val load by vm.state.collectAsStateWithLifecycle()
    val draft by vm.draft.collectAsStateWithLifecycle()
    CollectMessages(vm.messages, snackbar)
    Column(Modifier.fillMaxSize()) {
        ScreenHeader(stringResource(if (id == null) R.string.recipe_new else R.string.recipe_edit), onBack = onBack)
        LoadBox(load, onRetry = { vm.refresh(spinner = true) }) { existing ->
            var form by remember(existing, draft) {
                mutableStateOf(draft?.toForm() ?: existing?.toForm() ?: RecipeForm())
            }
            var url by remember { mutableStateOf("") }
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                if (id == null) {
                    SectionCard(stringResource(R.string.import_title)) {
                        OutlinedTextField(
                            value = url, onValueChange = { url = it }, singleLine = true,
                            label = { Text("https://…") }, modifier = Modifier.fillMaxWidth(),
                        )
                        OutlinedButton(onClick = { vm.import(url) }, enabled = url.startsWith("http")) {
                            Text(stringResource(R.string.import_go))
                        }
                    }
                }
                OutlinedTextField(form.title, { form = form.copy(title = it) }, label = { Text(stringResource(R.string.f_title)) }, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(form.description, { form = form.copy(description = it) }, label = { Text(stringResource(R.string.f_description)) }, modifier = Modifier.fillMaxWidth())
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(form.servings, { form = form.copy(servings = it) }, label = { Text(stringResource(R.string.f_servings)) }, modifier = Modifier.weight(1f))
                    OutlinedTextField(form.prep, { form = form.copy(prep = it) }, label = { Text(stringResource(R.string.f_prep)) }, modifier = Modifier.weight(1f))
                    OutlinedTextField(form.cook, { form = form.copy(cook = it) }, label = { Text(stringResource(R.string.f_cook)) }, modifier = Modifier.weight(1f))
                }
                OutlinedTextField(
                    form.ingredients, { form = form.copy(ingredients = it) },
                    label = { Text(stringResource(R.string.f_ingredients)) }, minLines = 6, modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    form.method, { form = form.copy(method = it) },
                    label = { Text(stringResource(R.string.f_method)) }, minLines = 6, modifier = Modifier.fillMaxWidth(),
                )
                Button(onClick = { vm.save(form, onSaved) }, enabled = form.title.isNotBlank()) {
                    Text(stringResource(R.string.save))
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}
