package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RecipeFilterTest {
    private val fields = listOf("Pasta Carbonara", "italiensk", "hurtig", "spaghetti", "æg", "bacon")

    @Test
    fun matchesAnyFieldAndEveryWord() {
        listOf("carbo", "#hurtig", "ITALIENSK", "bacon", "pasta æg", "", "  ").forEach {
            assertTrue(it, RecipeFilter.matches(it, fields))
        }
        assertFalse(RecipeFilter.matches("pasta kylling", fields))
        assertTrue(RecipeFilter.matches("creme brulee", listOf("Crème brûlée")))
    }

    @Test
    fun pages() {
        val xs = (0 until 45).toList()
        assertEquals(3, RecipeFilter.pageCount(45))
        assertEquals(1, RecipeFilter.pageCount(0))
        assertEquals(xs.take(20), RecipeFilter.page(xs, 0))
        assertEquals(listOf(40, 41, 42, 43, 44), RecipeFilter.page(xs, 9))
        assertEquals(emptyList<Int>(), RecipeFilter.page(emptyList<Int>(), 2))
    }
}
