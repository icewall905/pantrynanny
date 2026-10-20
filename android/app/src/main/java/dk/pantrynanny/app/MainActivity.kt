package dk.pantrynanny.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.SystemBarStyle
import androidx.activity.enableEdgeToEdge
import dk.pantrynanny.app.domain.ScanMode
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.List
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import dk.pantrynanny.app.ui.InventoryScreen
import dk.pantrynanny.app.ui.LocalImages
import dk.pantrynanny.app.ui.LoginScreen
import dk.pantrynanny.app.ui.PantryTheme
import dk.pantrynanny.app.ui.ProductDetailScreen
import dk.pantrynanny.app.ui.ScannerScreen
import dk.pantrynanny.app.ui.ScannerViewModel
import dk.pantrynanny.app.ui.ActivityScreen
import dk.pantrynanny.app.ui.AssistantScreen
import dk.pantrynanny.app.ui.MoreScreen
import dk.pantrynanny.app.ui.OverviewScreen
import dk.pantrynanny.app.ui.PlanScreen
import dk.pantrynanny.app.ui.RecipeDetailScreen
import dk.pantrynanny.app.ui.RecipeEditScreen
import dk.pantrynanny.app.ui.RecipesScreen
import dk.pantrynanny.app.ui.SettingsScreen
import dk.pantrynanny.app.ui.ShoppingScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // The app is always dark: light status/navigation bar icons regardless of the system theme.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(android.graphics.Color.TRANSPARENT),
        )
        val container = (application as PantryApp).container
        Shortcuts.publish(this)
        handleLaunch(intent)
        setContent {
            PantryTheme {
                Surface {
                    PantryRoot(container)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleLaunch(intent)
    }

    /** Launcher shortcuts: open the scanner in a mode, or the shopping list in the web app. */
    private fun handleLaunch(intent: Intent?) {
        val container = (application as PantryApp).container
        when (intent?.action) {
            Shortcuts.ACTION_SCAN_ADD -> container.requestedMode.value = ScanMode.ADD
            Shortcuts.ACTION_SCAN_REMOVE -> container.requestedMode.value = ScanMode.REMOVE
            Shortcuts.ACTION_SHOPPING -> container.requestedRoute.value = ROUTE_SHOPPING
        }
        // a shortcut is handled once; a later configuration change must not repeat it
        intent?.action = Intent.ACTION_MAIN
    }
}

// Five tabs: the scanner first (the app opens there for quick scans), inventory, food (recipes +
// meal plan), the assistant and "Mere" for everything else (incl. the shopping list). Detail screens keep their tab lit.
private const val ROUTE_SCAN = "scan"
private const val ROUTE_INVENTORY = "inventory?unknown={unknown}"
const val ROUTE_SHOPPING = "shopping"
private const val ROUTE_RECIPES = "recipes"
private const val ROUTE_PLAN = "plan"
private const val ROUTE_MORE = "more"
private const val ROUTE_PRODUCT = "product/{id}?register={register}"
private const val ROUTE_RECIPE = "recipe/{id}?servings={servings}&meal={meal}"
private const val ROUTE_RECIPE_EDIT = "recipe_edit?id={id}"
private const val ROUTE_OVERVIEW = "overview"
private const val ROUTE_ACTIVITY = "activity"
private const val ROUTE_ASSISTANT = "assistant"
private const val ROUTE_SETTINGS = "settings"

@Composable
fun PantryRoot(container: AppContainer) {
    val loggedIn by container.tokens.loggedIn.collectAsStateWithLifecycle()
    CompositionLocalProvider(LocalImages provides container.images) {
        if (loggedIn) MainScaffold(container) else LoginScreen(container)
    }
}

private enum class Tab(val route: String, val labelRes: Int) {
    SCAN(ROUTE_SCAN, R.string.nav_scan),
    INVENTORY("inventory", R.string.nav_inventory),
    FOOD(ROUTE_RECIPES, R.string.tab_food),
    ASSISTANT(ROUTE_ASSISTANT, R.string.nav_assistant),
    MORE(ROUTE_MORE, R.string.nav_more),
}

/** Which tab a screen belongs to (by its route pattern). */
private fun tabOf(route: String?): Tab = when (route?.substringBefore('/')?.substringBefore('?')) {
    null, ROUTE_SCAN -> Tab.SCAN
    "inventory", "product" -> Tab.INVENTORY
    ROUTE_ASSISTANT -> Tab.ASSISTANT
    ROUTE_RECIPES, ROUTE_PLAN, "recipe", "recipe_edit" -> Tab.FOOD
    else -> Tab.MORE
}

@Composable
private fun TabIcon(tab: Tab) {
    when (tab) {
        Tab.SCAN -> Icon(painterResource(R.drawable.ic_nav_scan), contentDescription = null)
        Tab.INVENTORY -> Icon(Icons.AutoMirrored.Filled.List, contentDescription = null)
        Tab.ASSISTANT -> Icon(Icons.Filled.Face, contentDescription = null)
        Tab.FOOD -> Icon(painterResource(R.drawable.ic_nav_food), contentDescription = null)
        Tab.MORE -> Icon(Icons.Filled.Menu, contentDescription = null)
    }
}

@Composable
private fun MainScaffold(container: AppContainer) {
    val nav = rememberNavController()
    val snackbar = remember { SnackbarHostState() }
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route
    val current = tabOf(route)

    fun go(target: String) {
        nav.navigate(target) {
            popUpTo(ROUTE_SCAN) { saveState = true }
            launchSingleTop = true
            restoreState = true
        }
    }

    // Launcher shortcuts: "Scan in/out" open the scanner, "Shopping list" its tab.
    val requested by container.requestedMode.collectAsStateWithLifecycle()
    LaunchedEffect(requested) {
        if (requested != null && route != null && route != ROUTE_SCAN) go(ROUTE_SCAN)
    }
    val requestedRoute by container.requestedRoute.collectAsStateWithLifecycle()
    LaunchedEffect(requestedRoute) {
        requestedRoute?.let {
            container.requestedRoute.value = null
            go(it)
        }
    }

    val openProduct: (String) -> Unit = { id -> nav.navigate("product/$id") }
    fun openUnknown() {
        nav.navigate("inventory?unknown=true") {
            popUpTo(ROUTE_SCAN)
            launchSingleTop = true
        }
    }
    val back: () -> Unit = { nav.popBackStack() }

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            NavigationBar {
                Tab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = current == tab,
                        onClick = { go(tab.route) },
                        icon = { TabIcon(tab) },
                        label = { Text(stringResource(tab.labelRes), maxLines = 1) },
                    )
                }
            }
        },
    ) { padding ->
        NavHost(nav, startDestination = ROUTE_SCAN, modifier = Modifier.padding(padding)) {
            composable(ROUTE_SCAN) {
                val vm: ScannerViewModel = viewModel(factory = viewModelFactory { initializer { ScannerViewModel(container) } })
                ScannerScreen(vm, snackbar, onRegisterProduct = { id -> nav.navigate("product/$id?register=true") })
            }
            composable(
                ROUTE_INVENTORY,
                arguments = listOf(navArgument("unknown") { type = NavType.BoolType; defaultValue = false }),
            ) { backStack ->
                InventoryScreen(
                    container,
                    onOpenProduct = openProduct,
                    startUnknown = backStack.arguments?.getBoolean("unknown") ?: false,
                )
            }
            composable(
                ROUTE_PRODUCT,
                arguments = listOf(navArgument("register") { type = NavType.BoolType; defaultValue = false }),
            ) { backStack ->
                val id = backStack.arguments?.getString("id") ?: ""
                val register = backStack.arguments?.getBoolean("register") ?: false
                ProductDetailScreen(container, id, snackbar, register = register, onBack = back)
            }
            composable(ROUTE_SHOPPING) { ShoppingScreen(container, snackbar, onBack = back) }
            composable(ROUTE_RECIPES) {
                RecipesScreen(
                    container, snackbar,
                    onOpen = { id -> nav.navigate("recipe/$id") },
                    onNew = { nav.navigate("recipe_edit") },
                    onPlan = { go(ROUTE_PLAN) },
                )
            }
            composable(ROUTE_PLAN) {
                PlanScreen(
                    container, snackbar,
                    onRecipes = { go(ROUTE_RECIPES) },
                    onOpenRecipe = { m ->
                        nav.navigate("recipe/${m.recipeId}?servings=${m.servings ?: ""}&meal=${m.id}")
                    },
                )
            }
            composable(
                ROUTE_RECIPE,
                arguments = listOf(
                    navArgument("servings") { type = NavType.StringType; nullable = true; defaultValue = null },
                    navArgument("meal") { type = NavType.StringType; nullable = true; defaultValue = null },
                ),
            ) { backStack ->
                val id = backStack.arguments?.getString("id") ?: ""
                RecipeDetailScreen(
                    container,
                    id = id,
                    servings = backStack.arguments?.getString("servings")?.toIntOrNull(),
                    mealId = backStack.arguments?.getString("meal")?.takeIf { it.isNotBlank() },
                    snackbar = snackbar,
                    onBack = back,
                    onEdit = { nav.navigate("recipe_edit?id=$id") },
                )
            }
            composable(
                ROUTE_RECIPE_EDIT,
                arguments = listOf(navArgument("id") { type = NavType.StringType; nullable = true; defaultValue = null }),
            ) { backStack ->
                val id = backStack.arguments?.getString("id")
                RecipeEditScreen(container, id, snackbar, onBack = back, onSaved = { saved ->
                    nav.popBackStack()
                    if (id == null) nav.navigate("recipe/$saved")
                })
            }
            composable(ROUTE_MORE) {
                MoreScreen(
                    container,
                    onOverview = { nav.navigate(ROUTE_OVERVIEW) },
                    onUnknown = { openUnknown() },
                    onActivity = { nav.navigate(ROUTE_ACTIVITY) },
                    onShopping = { nav.navigate(ROUTE_SHOPPING) },
                    onSettings = { nav.navigate(ROUTE_SETTINGS) },
                )
            }
            composable(ROUTE_OVERVIEW) {
                OverviewScreen(
                    container, snackbar, onBack = back, onOpenProduct = openProduct,
                    onOpenUnknown = { openUnknown() },
                    onOpenShopping = { go(ROUTE_SHOPPING) },
                )
            }
            composable(ROUTE_ACTIVITY) { ActivityScreen(container, snackbar, onBack = back, onOpenProduct = openProduct) }
            composable(ROUTE_ASSISTANT) { AssistantScreen(container, snackbar) }
            composable(ROUTE_SETTINGS) { SettingsScreen(container, onBack = back) }
        }
    }
}
