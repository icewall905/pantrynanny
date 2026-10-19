package dk.pantrynanny.app.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

// Same palette as the web app (web/src/index.css, dark theme): clean neutrals, one fresh green.
val AddColor = Color(0xFF12B76A)
val RemoveColor = Color(0xFFF04438)
val WarnColor = Color(0xFFFDB022)

private val PantryDark = darkColorScheme(
    primary = Color(0xFF2FD283),
    onPrimary = Color(0xFF00210F),
    primaryContainer = Color(0xFF0F2E1F),
    onPrimaryContainer = Color(0xFF9CF3C4),
    secondary = Color(0xFF86918C),
    onSecondary = Color(0xFF0A0E0C),
    secondaryContainer = Color(0xFF1D2622),
    onSecondaryContainer = Color(0xFFC3CCC7),
    tertiary = Color(0xFF53B1FD),
    onTertiary = Color(0xFF00213D),
    background = Color(0xFF0A0E0C),
    onBackground = Color(0xFFEEF3F0),
    surface = Color(0xFF0A0E0C),
    onSurface = Color(0xFFEEF3F0),
    surfaceVariant = Color(0xFF1D2622),
    onSurfaceVariant = Color(0xFFC3CCC7),
    surfaceContainerLowest = Color(0xFF070A09),
    surfaceContainerLow = Color(0xFF0F1412),
    surfaceContainer = Color(0xFF121815),
    surfaceContainerHigh = Color(0xFF18201C),
    surfaceContainerHighest = Color(0xFF1D2622),
    inverseSurface = Color(0xFFEEF3F0),
    inverseOnSurface = Color(0xFF121815),
    inversePrimary = Color(0xFF079455),
    outline = Color(0xFF3A4540),
    outlineVariant = Color(0xFF222B27),
    error = Color(0xFFFF7A6E),
    onError = Color(0xFF2A1210),
    errorContainer = Color(0xFF451915),
    onErrorContainer = Color(0xFFFFDAD6),
)

private val PantryShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(28.dp),
)

private val base = Typography()
private val PantryType = Typography(
    headlineLarge = base.headlineLarge.copy(fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp),
    headlineMedium = base.headlineMedium.copy(fontWeight = FontWeight.Bold, letterSpacing = (-0.4).sp),
    headlineSmall = base.headlineSmall.copy(fontWeight = FontWeight.SemiBold, letterSpacing = (-0.3).sp),
    titleLarge = base.titleLarge.copy(fontWeight = FontWeight.SemiBold, letterSpacing = (-0.2).sp),
    titleMedium = base.titleMedium.copy(fontWeight = FontWeight.SemiBold),
    labelLarge = base.labelLarge.copy(fontWeight = FontWeight.SemiBold, letterSpacing = 0.1.sp),
)

/** Always dark (matches the web app's default); the scanner's Add/Remove colours sit on top of it. */
@Composable
fun PantryTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = PantryDark, shapes = PantryShapes, typography = PantryType, content = content)
}
