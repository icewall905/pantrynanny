package dk.pantrynanny.app.data

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** Tracks whether the device has a default network (used for the online/offline indicator and sync triggers). */
class NetworkMonitor(context: Context) {
    private val cm = context.getSystemService(ConnectivityManager::class.java)

    private val _online = MutableStateFlow(computeOnline())
    val online: StateFlow<Boolean> = _online

    private fun computeOnline(): Boolean {
        val net = cm.activeNetwork ?: return false
        return cm.getNetworkCapabilities(net)?.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) == true
    }

    fun start(onRegained: () -> Unit) {
        try {
            cm.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) {
                    _online.value = true
                    onRegained()
                }

                override fun onLost(network: Network) {
                    _online.value = false
                }
            })
        } catch (_: Exception) {
            // Callback registration can fail on some OEM builds; the indicator then stays at its initial value.
        }
    }
}
