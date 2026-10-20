package dk.pantrynanny.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.AssistChip
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.ChatReplyDto
import dk.pantrynanny.app.data.remote.MealDto
import dk.pantrynanny.app.data.remote.ProposalDto
import dk.pantrynanny.app.data.remote.ShoppingItemDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonPrimitive

data class ChatEntry(val role: String, val text: String, val proposals: List<ProposalDto> = emptyList())

data class AssistantUi(
    val entries: List<ChatEntry> = emptyList(),
    val busy: Boolean = false,
    val error: String? = null,
    val done: Set<String> = emptySet(),
)

class AssistantViewModel(private val c: AppContainer) : ViewModel() {
    private val _ui = MutableStateFlow(AssistantUi())
    val ui: StateFlow<AssistantUi> = _ui.asStateFlow()
    val messages = MutableSharedFlow<UiMessage>(extraBufferCapacity = 8)

    fun send(text: String) {
        val q = text.trim()
        if (q.isEmpty() || _ui.value.busy) return
        val entries = _ui.value.entries + ChatEntry("user", q)
        _ui.value = _ui.value.copy(entries = entries, busy = true, error = null)
        viewModelScope.launch {
            val history = entries.takeLast(12).dropWhile { it.role != "user" }
            val body = buildJsonObject {
                put(
                    "messages",
                    JsonArray(history.map { buildJsonObject { put("role", JsonPrimitive(it.role)); put("content", JsonPrimitive(it.text.take(4000))) } }),
                )
                put("locale", JsonPrimitive(if (java.util.Locale.getDefault().language == "en") "en" else "da"))
            }
            when (val r = c.api.post("api/ai/chat", body, ChatReplyDto.serializer(), slow = true)) {
                is ApiResult.Ok -> _ui.value = _ui.value.copy(
                    entries = _ui.value.entries + ChatEntry("assistant", r.value.reply, r.value.proposals),
                    busy = false,
                )
                is ApiResult.NetworkError -> _ui.value = _ui.value.copy(busy = false, error = r.cause.message ?: "offline")
                is ApiResult.HttpError -> _ui.value = _ui.value.copy(busy = false, error = r.detail ?: "HTTP ${r.code}")
            }
        }
    }

    fun clear() {
        _ui.value = AssistantUi()
    }

    /** A suggested action runs only when the user taps it, through the normal endpoints / op queue. */
    fun runProposal(p: ProposalDto) {
        if (p.id in _ui.value.done) return
        viewModelScope.launch(Dispatchers.IO) {
            val pl: JsonObject = p.payload
            fun s(k: String) = pl[k]?.jsonPrimitive?.contentOrNull
            fun d(k: String) = pl[k]?.jsonPrimitive?.doubleOrNull
            val ok = when (p.kind) {
                "shopping_add" -> c.api.post(
                    "api/shopping",
                    buildJsonObject {
                        val pid = s("product_id")
                        if (pid != null) put("product_id", JsonPrimitive(pid)) else put("name", JsonPrimitive(s("name") ?: ""))
                        put("quantity", JsonPrimitive(d("quantity") ?: 1.0))
                    },
                    ShoppingItemDto.serializer(),
                ) is ApiResult.Ok
                "meal_plan" -> c.api.post("api/meal-plan", pl, MealDto.serializer()) is ApiResult.Ok
                "consume" -> {
                    val pid = s("product_id")
                    val q = d("quantity")
                    if (pid != null && q != null) {
                        val queued = c.scanRepository.enqueueOp("remove", pid, q)
                        c.requestSync()
                        queued != null
                    } else {
                        false
                    }
                }
                else -> false
            }
            if (ok) _ui.value = _ui.value.copy(done = _ui.value.done + p.id)
            messages.tryEmit(UiMessage(if (ok) R.string.edit_saved else R.string.edit_offline))
        }
    }
}

@Composable
fun AssistantScreen(container: AppContainer, snackbar: SnackbarHostState, onBack: () -> Unit) {
    val vm: AssistantViewModel = viewModel(factory = viewModelFactory { initializer { AssistantViewModel(container) } })
    val ui by vm.ui.collectAsStateWithLifecycle()
    CollectMessages(vm.messages, snackbar)
    var text by remember { mutableStateOf("") }
    val list = rememberLazyListState()
    LaunchedEffect(ui.entries.size, ui.busy) {
        val n = ui.entries.size + (if (ui.busy) 1 else 0)
        if (n > 0) list.animateScrollToItem(n - 1)
    }
    Column(Modifier.fillMaxSize()) {
        ScreenHeader(stringResource(R.string.nav_assistant), onBack = onBack, subtitle = stringResource(R.string.assistant_hint))
        LazyColumn(Modifier.weight(1f).padding(horizontal = 16.dp), state = list, verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (ui.entries.isEmpty()) {
                item {
                    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf(R.string.ask_1, R.string.ask_2, R.string.ask_3).forEach { res ->
                            val q = stringResource(res)
                            AssistChip(onClick = { vm.send(q) }, label = { Text(q) })
                        }
                    }
                }
            }
            items(ui.entries.withIndex().toList(), key = { it.index }) { (_, e) ->
                SectionCard(if (e.role == "user") stringResource(R.string.you) else stringResource(R.string.nav_assistant)) {
                    Text(e.text.replace("**", ""))
                    e.proposals.forEach { p ->
                        val done = p.id in ui.done
                        OutlinedButton(onClick = { vm.runProposal(p) }, enabled = !done, modifier = Modifier.fillMaxWidth()) {
                            Text((if (done) "✓ " else "") + proposalLabel(p.kind) + ": " + p.label)
                        }
                    }
                }
            }
            if (ui.busy) {
                item {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        CircularProgressIndicator(Modifier.padding(4.dp))
                        Text(stringResource(R.string.thinking))
                    }
                }
            }
            ui.error?.let { err ->
                item { Text(stringResource(R.string.edit_failed, err), color = MaterialTheme.colorScheme.error, fontWeight = FontWeight.SemiBold) }
            }
        }
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text(stringResource(R.string.ask_hint)) },
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = {
                vm.send(text)
                text = ""
            }, enabled = !ui.busy) {
                Icon(Icons.AutoMirrored.Filled.Send, contentDescription = stringResource(R.string.send))
            }
        }
    }
}

@Composable
private fun proposalLabel(kind: String): String = when (kind) {
    "shopping_add" -> stringResource(R.string.prop_shopping)
    "meal_plan" -> stringResource(R.string.prop_plan)
    "consume" -> stringResource(R.string.prop_consume)
    else -> kind
}
