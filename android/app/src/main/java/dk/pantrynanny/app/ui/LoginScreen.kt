package dk.pantrynanny.app.ui

import android.os.Build
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import dk.pantrynanny.app.AppContainer
import dk.pantrynanny.app.R
import dk.pantrynanny.app.data.DEFAULT_SERVER_URL
import dk.pantrynanny.app.data.remote.ApiClient
import dk.pantrynanny.app.data.remote.ApiResult
import kotlinx.coroutines.launch

class LoginViewModel(private val c: AppContainer) : ViewModel() {
    var serverUrl by mutableStateOf(DEFAULT_SERVER_URL)
    var username by mutableStateOf("")
    var password by mutableStateOf("")
    var busy by mutableStateOf(false)
    private var wipeConfirmed = false
    var errorRes by mutableStateOf<Int?>(null)
    var errorDetail by mutableStateOf<String?>(null)

    init {
        viewModelScope.launch { serverUrl = c.settings.current().serverUrl }
    }

    fun login() {
        val url = serverUrl.trim().trimEnd('/')
        val schemeOk = url.startsWith("http://") || url.startsWith("https://")
        if (!schemeOk || ApiClient.buildUrl(url, "") == null) {
            errorRes = R.string.error_url_invalid
            errorDetail = null
            return
        }
        if (url.startsWith("http://") && !c.isDebuggable) {
            errorRes = R.string.error_http_release
            errorDetail = null
            return
        }
        if (username.isBlank() || password.isEmpty()) {
            errorRes = R.string.error_missing_credentials
            errorDetail = null
            return
        }
        busy = true
        errorRes = null
        errorDetail = null
        viewModelScope.launch {
            when (val r = c.api.login(url, username.trim(), password, Build.MODEL ?: "Android")) {
                is ApiResult.Ok -> {
                    val me = r.value.me
                    // The local database belongs to one server + household. Switching: wipe it, but
                    // never silently lose queued ops - ask for a second tap first.
                    val owner = url + "|" + (me.household?.id ?: "")
                    val previous = c.settings.current().cacheOwner
                    if (previous != null && previous != owner) {
                        val unsynced = c.db.pendingOpDao().totalOpCount()
                        if (unsynced > 0 && !wipeConfirmed) {
                            wipeConfirmed = true
                            errorRes = R.string.warn_other_server_pending
                            errorDetail = unsynced.toString()
                            busy = false
                            return@launch
                        }
                        c.wipeLocalData()
                    }
                    wipeConfirmed = false
                    c.settings.setServerUrl(url)
                    c.settings.setCacheOwner(owner)
                    c.settings.setUserLabel(me.user?.let { it.displayName ?: it.username })
                    me.settings?.let { c.settings.setServerSettings(it.scanRearmMs, it.removeModeTimeoutMin) }
                    password = ""
                    c.tokens.save(r.value.token) // flips the app to the logged-in UI
                    c.onLoggedIn()
                }
                is ApiResult.HttpError -> {
                    wipeConfirmed = false
                    errorRes = when (r.code) {
                        400, 401, 403 -> R.string.error_bad_credentials
                        429 -> R.string.error_rate_limited
                        else -> R.string.error_generic
                    }
                    errorDetail = r.detail ?: "HTTP ${r.code}"
                }
                is ApiResult.NetworkError -> {
                    errorRes = R.string.error_network
                    errorDetail = r.cause.message
                }
            }
            busy = false
        }
    }
}

@Composable
fun LoginScreen(container: AppContainer) {
    val vm: LoginViewModel = viewModel(factory = viewModelFactory { initializer { LoginViewModel(container) } })
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(stringResource(R.string.app_name), style = MaterialTheme.typography.headlineLarge)
        Spacer(Modifier.height(4.dp))
        Text(stringResource(R.string.login_subtitle))
        Spacer(Modifier.height(24.dp))
        OutlinedTextField(
            value = vm.serverUrl,
            onValueChange = { vm.serverUrl = it },
            label = { Text(stringResource(R.string.server_url)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = vm.username,
            onValueChange = { vm.username = it },
            label = { Text(stringResource(R.string.username)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = vm.password,
            onValueChange = { vm.password = it },
            label = { Text(stringResource(R.string.password)) },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))
        vm.errorRes?.let { res ->
            Text(stringResource(res), color = MaterialTheme.colorScheme.error)
            vm.errorDetail?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
            Spacer(Modifier.height(8.dp))
        }
        Button(onClick = vm::login, enabled = !vm.busy, modifier = Modifier.fillMaxWidth()) {
            if (vm.busy) CircularProgressIndicator(Modifier.height(20.dp)) else Text(stringResource(R.string.login))
        }
    }
}
