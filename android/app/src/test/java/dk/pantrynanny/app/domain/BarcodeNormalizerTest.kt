package dk.pantrynanny.app.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
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
        assertEquals("local:", BarcodeNormalizer.normalize("").code)
    }

    @Test
    fun checkDigitHelpers() {
        assertTrue(BarcodeNormalizer.hasValidCheckDigit("4006381333931"))
        assertFalse(BarcodeNormalizer.hasValidCheckDigit("4006381333930"))
        assertNull(BarcodeNormalizer.expandUpcE("1234567"))
    }
}
