package dk.pantrynanny.app.domain

import java.time.LocalDate

/** One-tap expiry chip shown after an add was applied ("+3 d", "+1 u", "+1 m", "+6 m", "Ingen"). */
sealed interface ExpiryChip {
    data class Days(val n: Int) : ExpiryChip
    data class Weeks(val n: Int) : ExpiryChip
    data class Months(val n: Int) : ExpiryChip
    data object None : ExpiryChip
}

/** A location as far as the "where did the add go" rule needs it. */
data class PlaceLocation(val id: String, val isDefault: Boolean, val sortOrder: Int)

/** Pure logic behind the expiry/location chips on the last-scanned card. */
object Placement {
    val PRESETS: List<ExpiryChip> = listOf(
        ExpiryChip.Days(3), ExpiryChip.Weeks(1), ExpiryChip.Months(1), ExpiryChip.Months(6), ExpiryChip.None,
    )

    /** The expiry date a chip stands for, from the device's local [today]; null = no expiry. */
    fun expiryDate(chip: ExpiryChip, today: LocalDate): LocalDate? = when (chip) {
        is ExpiryChip.Days -> today.plusDays(chip.n.toLong())
        is ExpiryChip.Weeks -> today.plusWeeks(chip.n.toLong())
        is ExpiryChip.Months -> today.plusMonths(chip.n.toLong())
        ExpiryChip.None -> null
    }

    /**
     * The chip matching the category's `default_expiry_days`: a preset when it is exactly that many days
     * (3 → "+3 d", 7 → "+1 u"), otherwise an extra "+N d" chip. Months are never matched by day count,
     * since a month is not a fixed number of days.
     */
    fun categoryChip(defaultExpiryDays: Int?): ExpiryChip? {
        val d = defaultExpiryDays ?: return null
        if (d < 0) return null
        return PRESETS.firstOrNull { it == ExpiryChip.Days(d) || (it is ExpiryChip.Weeks && it.n * 7 == d) }
            ?: ExpiryChip.Days(d)
    }

    /** Chips to show: the presets, with the category's own chip first when it is not one of them. */
    fun chips(defaultExpiryDays: Int?): List<ExpiryChip> {
        val cat = categoryChip(defaultExpiryDays) ?: return PRESETS
        return if (cat in PRESETS) PRESETS else listOf(cat) + PRESETS
    }

    /**
     * Where the add went, mirroring the server: the op's own location, else the product's place, else
     * the category's place, else the household default (is_default first, then sort order).
     * Candidates that are not (or no longer) in [locations] are skipped.
     */
    fun currentLocation(
        opLocationId: String?,
        productLocationId: String?,
        categoryLocationId: String?,
        locations: List<PlaceLocation>,
    ): String? {
        val ids = locations.mapTo(HashSet()) { it.id }
        listOf(opLocationId, productLocationId, categoryLocationId).firstOrNull { it != null && it in ids }?.let { return it }
        return locations.sortedWith(compareBy({ !it.isDefault }, { it.sortOrder })).firstOrNull()?.id
    }
}
