package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class BarcodeNormalizerTest {
    @Test
    fun ean13IsPaddedToGtin14() {
        val r = BarcodeNormalizer.normalize("4006381333931", "ean_13")
        assertEquals("04006381333931", r.code)
        assertEquals("ean_13", r.symbology)
        assertTrue(r.valid)
    }

    @Test
    fun whitespaceIsStripped() {
        assertEquals("04006381333931", BarcodeNormalizer.normalize(" 4006381333931\n").code)
    }

    @Test
    fun ean8IsPadded() {
        val r = BarcodeNormalizer.normalize("96385074", "ean_8")
        assertEquals("00000096385074", r.code)
        assertTrue(r.valid)
    }

    @Test
    fun upcAIsPadded() {
        val r = BarcodeNormalizer.normalize("036000291452", "upc_a")
        assertEquals("00036000291452", r.code)
        assertTrue(r.valid)
    }

    @Test
    fun gtin14IsKept() {
        val r = BarcodeNormalizer.normalize("04006381333931")
        assertEquals("04006381333931", r.code)
        assertTrue(r.valid)
    }

    @Test
    fun upcEWithHintExpandsToUpcA() {
        val r = BarcodeNormalizer.normalize("04252614", "upc_e")
        assertEquals("00042100005264", r.code) // UPC-A 042100005264
        assertTrue(r.valid)
        assertEquals("upc_e", r.symbology)
    }

    @Test
    fun sixDigitUpcEExpands() {
        val r = BarcodeNormalizer.normalize("425261")
        assertEquals("00042100005264", r.code)
        assertTrue(r.valid)
    }

    @Test
    fun upcEWithWrongCheckDigitIsLocal() {
        val r = BarcodeNormalizer.normalize("04252615", "upc_e")
        assertEquals("local:04252615", r.code)
        assertFalse(r.valid)
    }

    @Test
    fun eightDigitsWithoutUpcEHintIsEan8() {
        assertEquals("00000096385074", BarcodeNormalizer.normalize("96385074").code)
    }

    @Test
    fun inStoreEan13UsesFirstSevenDigits() {
        val a = BarcodeNormalizer.normalize("2012345678903", "ean_13")
        assertEquals("instore:2012345", a.code)
        assertTrue(a.valid)
        // same item reference, different price/weight part -> same code
        val b = BarcodeNormalizer.normalize("2012345123458", "ean_13")
        assertEquals(8, BarcodeNormalizer.checkDigitFor("201234512345"))
        assertEquals("instore:2012345", b.code)
    }

    @Test
    fun invalidChecksumBecomesLocal() {
        val r = BarcodeNormalizer.normalize("4006381333932", "ean_13")
        assertEquals("local:4006381333932", r.code)
        assertFalse(r.valid)
    }

    @Test
    fun nonDigitCodesAreLocal() {
        val r = BarcodeNormalizer.normalize("ABC-123", "code_128")
        assertEquals("local:ABC-123", r.code)
        assertFalse(r.valid)
        assertEquals("code_128", r.symbology)
    }

    @Test
    fun nonGtinSymbologiesAreLocalEvenIfDigits() {
        for (h in listOf("code_128", "code_39", "qr", "data_matrix")) {
            val r = BarcodeNormalizer.normalize("  4006381333931 \n", h)
            assertEquals("local:4006381333931", r.code)
            assertFalse(r.valid)
            assertEquals(h, r.symbology)
        }
    }

    @Test
    fun localUsesTrimmedRawAndDefaultsToOther() {
        val r = BarcodeNormalizer.normalize("  ABC 1 \n")
        assertEquals("local:ABC 1", r.code)
        assertEquals("other", r.symbology)
    }

    @Test
    fun itfFourteenDigitsAndSymbologyFromLength() {
        assertEquals("itf", BarcodeNormalizer.normalize("04006381333931", "itf").symbology)
        assertEquals("ean_13", BarcodeNormalizer.normalize("4006381333931").symbology)
        assertEquals("ean_8", BarcodeNormalizer.normalize("96385074").symbology)
        assertEquals("upc_a", BarcodeNormalizer.normalize("036000291452").symbology)
    }

    @Test
    fun oddLengthsAreLocal() {
        assertEquals("local:12345", BarcodeNormalizer.normalize("12345").code)
    }

    // Parity vectors mirrored from backend/tests/test_barcodes.py (keep the two lists in sync).
    @Test
    fun stripParityVectors() {
        val raws = listOf(
            "5701234567899",
            "\t5701234567899\r\n",
            "\u001D5701234567899\u001D", // GS1 group separator
            "\u001C\u001E\u001F5701234567899",
            "\u00855701234567899\u00A0", // NEL, NBSP
            "\uFEFF5701234567899", // BOM
            "\u000B\u000C 5701234567899 ",
            "5 701234 567899", // inner ASCII whitespace ignored
        )
        for (raw in raws) {
            val r = BarcodeNormalizer.normalize(raw)
            assertEquals(raw, "05701234567899", r.code)
            assertTrue(raw, r.valid)
        }
    }

    @Test
    fun nonAsciiDigitsAndInnerSeparatorsAreLocal() {
        val raws = listOf(
            "570123456789\u00B2", // superscript two
            "\u0665\u0667\u0660\u0661234567899", // Arabic-Indic digits
            "5701234567899\u200B", // zero-width space is NOT stripped
            "57\u00A001234567899", // inner NBSP is not ignorable
            "57\u001D01234567899", // inner separators are not ignorable
            "\uFF15701234567899", // full-width digit
        )
        for (raw in raws) {
            val r = BarcodeNormalizer.normalize(raw)
            assertFalse(raw, r.valid)
            assertEquals("local:" + BarcodeNormalizer.strip(raw), r.code)
        }
    }

    @Test
    fun crossImplementationVectors() {
        val vectors = listOf(
            "5701234567899\u001D" to "05701234567899",
            "\u001D5701234567899" to "05701234567899",
            "\uFEFF5701234567899" to "05701234567899",
            " 5701234567899\u0085" to "05701234567899",
            "570 1234 567899" to "05701234567899",
            "\u200B5701234567899" to "local:\u200B5701234567899",
            "570123456789\u00B2" to "local:570123456789\u00B2",
            "5701234567892\u001D" to "local:5701234567892",
            "\uFF15\uFF17\uFF10\uFF11\uFF12\uFF13\uFF14\uFF15\uFF16\uFF17\uFF18\uFF19\uFF19" to
                "local:\uFF15\uFF17\uFF10\uFF11\uFF12\uFF13\uFF14\uFF15\uFF16\uFF17\uFF18\uFF19\uFF19",
            "\u0665\u0667\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u0669" to
                "local:\u0665\u0667\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669\u0669",
        )
        for ((raw, code) in vectors) assertEquals(raw, code, BarcodeNormalizer.normalize(raw).code)
    }

    @Test
    fun unicodeSpacesOutsideTheRuleAreKept() {
        // Kotlin trim() would strip these; the backend does not.
        assertEquals("local:\u20035701234567899", BarcodeNormalizer.normalize("\u20035701234567899").code)
        assertEquals("local:57\u200301234567899", BarcodeNormalizer.normalize("57\u200301234567899").code)
    }

    @Test
    fun blankAfterStripIsRejected() {
        for (raw in listOf("", "  ", "\t\n", "\u001D\u001C", "\u00A0\uFEFF\u0085")) {
            assertTrue(raw, BarcodeNormalizer.isBlank(raw))
            assertThrows(IllegalArgumentException::class.java) { BarcodeNormalizer.normalize(raw) }
        }
        assertFalse(BarcodeNormalizer.isBlank(" 1 "))
    }

    @Test
    fun checkDigitHelpers() {
        assertTrue(BarcodeNormalizer.hasValidCheckDigit("4006381333931"))
        assertFalse(BarcodeNormalizer.hasValidCheckDigit("4006381333930"))
        assertNull(BarcodeNormalizer.expandUpcE("1234567"))
    }
}
