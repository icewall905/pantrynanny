package dk.pantrynanny.app

import android.content.Context
import android.content.Intent
import androidx.core.content.pm.ShortcutInfoCompat
import androidx.core.content.pm.ShortcutManagerCompat
import androidx.core.graphics.drawable.IconCompat

/** Long-press the launcher icon: "Scan in", "Scan out", "Shopping list". */
object Shortcuts {
    const val ACTION_SCAN_ADD = "dk.pantrynanny.app.action.SCAN_ADD"
    const val ACTION_SCAN_REMOVE = "dk.pantrynanny.app.action.SCAN_REMOVE"
    const val ACTION_SHOPPING = "dk.pantrynanny.app.action.SHOPPING"

    /** Dynamic (not manifest) shortcuts so they work for the ".debug" build too. */
    fun publish(context: Context) {
        val list = listOf(
            shortcut(context, "scan_add", ACTION_SCAN_ADD, R.string.shortcut_scan_add, R.drawable.ic_shortcut_add),
            shortcut(context, "scan_remove", ACTION_SCAN_REMOVE, R.string.shortcut_scan_remove, R.drawable.ic_shortcut_remove),
            shortcut(context, "shopping", ACTION_SHOPPING, R.string.shortcut_shopping, R.drawable.ic_shortcut_cart),
        )
        runCatching { ShortcutManagerCompat.setDynamicShortcuts(context, list) }
    }

    private fun shortcut(context: Context, id: String, action: String, label: Int, icon: Int): ShortcutInfoCompat =
        ShortcutInfoCompat.Builder(context, id)
            .setShortLabel(context.getString(label))
            .setIcon(IconCompat.createWithResource(context, icon))
            .setIntent(Intent(context, MainActivity::class.java).setAction(action))
            .build()
}
