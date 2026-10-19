package dk.pantrynanny.app.domain

data class NormalizedBarcode(val code: String, val symbology: String?, val valid: Boolean)

/**
 * Kotlin port of backend/pantrynanny/services/barcodes.py `normalize` (docs/api-contract.md section 6).
 * Keep in parity: BarcodeNormalizerTest mirrors the backend parity vectors.
 */
object BarcodeNormalizer {

    private val NON_GTIN = setOf("qr", "data_matrix", "code_128", "code_39")
    private val KNOWN = setOf(
        "ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "itf", "qr", "data_matrix", "other",
    )

    /**
     * Characters stripped from BOTH ENDS of a scanned value (must equal the backend rule exactly):
     * ASCII whitespace (U+0009-000D, U+0020), U+001C-001F (incl. the GS1 group separator U+001D),
     * U+0085, U+00A0 and U+FEFF. Deliberately not Kotlin trim()/isWhitespace(), which differ.
     */
    fun isStripChar(c: Char): Boolean =
        c in '\u0009'..'\u000D' || c == ' ' || c in '\u001C'..'\u001F' ||
            c == '\u0085' || c == '\u00A0' || c == '\uFEFF'

    fun strip(raw: String): String = raw.trim(::isStripChar)

    /** True when nothing is left after stripping: such a value is invalid and must not be enqueued. */
    fun isBlank(raw: String): Boolean = strip(raw).isEmpty()

    private fun isAsciiWhitespace(c: Char): Boolean = c in '\u0009'..'\u000D' || c == ' '

    /** @throws IllegalArgumentException when [raw] is blank after stripping (check [isBlank] first). */
    fun normalize(raw: String, symbologyHint: String? = null): NormalizedBarcode {
        val stripped = strip(raw)
        require(stripped.isNotEmpty()) { "empty barcode" }
        val hint = symbologyHint?.takeIf { it in KNOWN }
        // Non-GTIN symbologies never take the GTIN path (same as the backend).
        if (hint in NON_GTIN) return local(stripped, hint)

        // Inner ASCII whitespace is ignored; digits means ASCII 0-9 only.
        val digits = stripped.filterNot(::isAsciiWhitespace)
        if (digits.isEmpty() || !digits.all { it in '0'..'9' }) return local(stripped, hint)

        val n = digits.length
        if (n == 6 || (n == 8 && hint == "upc_e")) {
            val expanded = expandUpcE(digits) ?: return local(stripped, hint)
            return NormalizedBarcode(expanded.padStart(14, '0'), "upc_e", true)
        }

        val kind = when (n) {
            8 -> "ean_8"
            12 -> "upc_a"
            13 -> "ean_13"
            14 -> "itf"
            else -> return local(stripped, hint)
        }
        if (!hasValidCheckDigit(digits)) return local(stripped, hint)

        if (n == 13 && digits.substring(0, 2).toInt() in 20..29) {
            return NormalizedBarcode("instore:" + digits.substring(0, 7), "ean_13", true)
        }
        return NormalizedBarcode(digits.padStart(14, '0'), kind, true)
    }

    private fun local(strippedRaw: String, symbology: String?) =
        NormalizedBarcode("local:$strippedRaw", symbology ?: "other", false)

    /** Mod-10 (GS1) check over the whole string, the last digit being the check digit. */
    fun hasValidCheckDigit(digits: String): Boolean {
        if (digits.length < 2 || !digits.all { it in '0'..'9' }) return false
        return checkDigitFor(digits.dropLast(1)) == digits.last() - '0'
    }

    /** Check digit for a GTIN body (all digits except the check digit). */
    fun checkDigitFor(body: String): Int {
        var sum = 0
        var weight = 3
        for (i in body.length - 1 downTo 0) {
            sum += (body[i] - '0') * weight
            weight = if (weight == 3) 1 else 3
        }
        return (10 - sum % 10) % 10
    }

    /**
     * Expand UPC-E to UPC-A. Accepts 6 digits (number system 0 assumed, check digit computed) or
     * 8 digits (number system + 6 + check digit). Returns null if malformed or the check digit is wrong.
     */
    fun expandUpcE(input: String): String? {
        val ns: Char
        val body: String
        val givenCheck: Int?
        when (input.length) {
            6 -> {
                ns = '0'; body = input; givenCheck = null
            }
            8 -> {
                ns = input[0]; body = input.substring(1, 7); givenCheck = input[7] - '0'
            }
            else -> return null
        }
        if (ns != '0' && ns != '1') return null
        val d = body
        val manufacturerAndProduct = when (d[5]) {
            '0', '1', '2' -> "" + d[0] + d[1] + d[5] + "00" + "00" + d[2] + d[3] + d[4]
            '3' -> "" + d[0] + d[1] + d[2] + "00" + "000" + d[3] + d[4]
            '4' -> "" + d[0] + d[1] + d[2] + d[3] + "0" + "0000" + d[4]
            else -> "" + d[0] + d[1] + d[2] + d[3] + d[4] + "0000" + d[5]
        }
        val upcABody = ns + manufacturerAndProduct
        val check = checkDigitFor(upcABody)
        if (givenCheck != null && givenCheck != check) return null
        return upcABody + check
    }
}
