package dk.pantrynanny.app.ui

import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.remote.ApiResult
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * Base for screens that show server data (shopping list, recipes, ...): loads [fetch] into
 * [state], and runs actions with a snackbar message and a refresh afterwards.
 */
abstract class RemoteVm<T>(protected val c: AppContainer) : ViewModel() {
    private val _state = MutableStateFlow<Load<T>>(Load.Loading)
    val state: StateFlow<Load<T>> = _state.asStateFlow()

    private val _messages = MutableSharedFlow<UiMessage>(extraBufferCapacity = 8)
    val messages: SharedFlow<UiMessage> = _messages.asSharedFlow()

    protected abstract suspend fun fetch(): ApiResult<T>

    /** Reload; keeps showing the old data while it loads unless [spinner] is set. */
    fun refresh(spinner: Boolean = false) {
        viewModelScope.launch {
            if (spinner || _state.value !is Load.Ok) _state.value = Load.Loading
            _state.value = fetch().toLoad()
        }
    }

    protected fun message(res: Int, arg: String? = null) {
        _messages.tryEmit(UiMessage(res, arg))
    }

    /** Run a server action; on success show [okRes] (if any) and reload. */
    protected fun act(okRes: Int?, okArg: String? = null, block: suspend () -> ApiResult<*>) {
        viewModelScope.launch {
            when (val r = block()) {
                is ApiResult.Ok -> {
                    okRes?.let { message(it, okArg) }
                    _state.value = fetch().toLoad()
                }
                is ApiResult.NetworkError -> message(R.string.edit_offline)
                is ApiResult.HttpError -> message(R.string.edit_failed, r.detail ?: "HTTP ${r.code}")
            }
        }
    }
}

/** Show a ViewModel's messages in the shared snackbar. */
@Composable
fun CollectMessages(messages: SharedFlow<UiMessage>, snackbar: SnackbarHostState) {
    val context = LocalContext.current
    LaunchedEffect(messages) {
        messages.collect { msg ->
            snackbar.currentSnackbarData?.dismiss()
            launch { snackbar.showSnackbar(msg.resolve(context), duration = SnackbarDuration.Short) }
        }
    }
}
