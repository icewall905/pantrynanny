package dk.pantrynanny.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import dk.pantrynanny.app.ui.InventoryScreen
import dk.pantrynanny.app.ui.LoginScreen
import dk.pantrynanny.app.ui.PantryTheme
import dk.pantrynanny.app.ui.ProductDetailScreen
import dk.pantrynanny.app.ui.ScannerScreen
import dk.pantrynanny.app.ui.ScannerViewModel
import dk.pantrynanny.app.ui.SettingsScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as PantryApp).container
        setContent {
            PantryTheme {
                Surface {
                    PantryRoot(container)
                }
            }
        }
    }
}

private const val ROUTE_SCAN = "scan"
private const val ROUTE_INVENTORY = "inventory"
private const val ROUTE_PRODUCT = "product/{id}"
private const val ROUTE_SETTINGS = "settings"

@Composable
fun PantryRoot(container: AppContainer) {
    val loggedIn by container.tokens.loggedIn.collectAsStateWithLifecycle()
    if (loggedIn) MainScaffold(container) else LoginScreen(container)
}

private data class NavItem(val route: String, val labelRes: Int, val icon: ImageVector)

@Composable
private fun MainScaffold(container: AppContainer) {
    val nav = rememberNavController()
    val snackbar = remember { SnackbarHostState() }
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route

    val items = listOf(
        NavItem(ROUTE_SCAN, R.string.nav_scan, Icons.Filled.Search),
        NavItem(ROUTE_INVENTORY, R.string.nav_inventory, Icons.AutoMirrored.Filled.List),
        NavItem(ROUTE_SETTINGS, R.string.nav_settings, Icons.Filled.Settings),
    )

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            NavigationBar {
                items.forEach { item ->
                    val selected = route == item.route || (item.route == ROUTE_INVENTORY && route == ROUTE_PRODUCT)
                    NavigationBarItem(
                        selected = selected,
                        onClick = {
                            nav.navigate(item.route) {
                                popUpTo(ROUTE_SCAN)
                                launchSingleTop = true
                            }
                        },
                        icon = { Icon(item.icon, contentDescription = null) },
                        label = { Text(stringResource(item.labelRes)) },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(nav, startDestination = ROUTE_SCAN, modifier = Modifier.padding(padding)) {
            composable(ROUTE_SCAN) {
                val vm: ScannerViewModel = viewModel(factory = viewModelFactory { initializer { ScannerViewModel(container) } })
                ScannerScreen(vm, snackbar)
            }
            composable(ROUTE_INVENTORY) {
                InventoryScreen(container, onOpenProduct = { id -> nav.navigate("product/$id") })
            }
            composable(ROUTE_PRODUCT) { backStack ->
                val id = backStack.arguments?.getString("id") ?: ""
                ProductDetailScreen(container, id, snackbar, onBack = { nav.popBackStack() })
            }
            composable(ROUTE_SETTINGS) {
                SettingsScreen(container)
            }
        }
    }
}
