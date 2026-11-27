package dk.pantrynanny.app.domain

import java.text.Normalizer

/** Live filtering and paging for the recipe list ("Hvad kan vi lave?"). */
object RecipeFilter {
    const val PAGE_SIZE = 20

    private val marks = Regex("\\p{M}+")

    private fun fold(s: String) = Normalizer.normalize(s.lowercase(), Normalizer.Form.NFD).replace(marks, "")

    /** Every word of [query] must appear in one of [fields]; `#tag` is the same as `tag`. */
    fun matches(query: String, fields: List<String>): Boolean {
        val words = fold(query).split(Regex("\\s+")).map { it.removePrefix("#") }.filter { it.isNotEmpty() }
        if (words.isEmpty()) return true
        val hay = fold(fields.joinToString("\n"))
        return words.all { hay.contains(it) }
    }

    /** Tagged anti-inflammatory (Mealie's "Anti-Inflammatory"; spelling and dashes do not matter). */
    fun isAntiInflammatory(tags: List<String>): Boolean =
        tags.any { fold(it).replace(Regex("[^a-z]"), "") in setOf("antiinflammatory", "antiinflammatorisk") }

    fun pageCount(size: Int, pageSize: Int = PAGE_SIZE) = maxOf(1, (size + pageSize - 1) / pageSize)

    /** The 0-based [page] (clamped) of [items]. */
    fun <T> page(items: List<T>, page: Int, pageSize: Int = PAGE_SIZE): List<T> {
        val p = page.coerceIn(0, pageCount(items.size, pageSize) - 1)
        return items.drop(p * pageSize).take(pageSize)
    }
}
