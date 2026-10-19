"""Barcode normalisation (API contract section 6). Pure functions, no I/O."""

import re
from dataclasses import dataclass

NON_GTIN_SYMBOLOGIES = {"qr", "data_matrix", "code_128", "code_39"}
SYMBOLOGIES = {
    "ean_13",
    "ean_8",
    "upc_a",
    "upc_e",
    "code_128",
    "code_39",
    "itf",
    "qr",
    "data_matrix",
    "other",
}
_WS = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NormalizedBarcode:
    code: str
    raw: str
    symbology: str | None
    valid: bool


def gtin_check_digit(body: str) -> int:
    """Mod-10 check digit for the digits *without* the check digit (GS1 algorithm)."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def has_valid_check_digit(digits: str) -> bool:
    return (
        len(digits) >= 2 and digits.isdigit() and gtin_check_digit(digits[:-1]) == int(digits[-1])
    )


def expand_upc_e(six: str, number_system: str = "0") -> str:
    """Expand a 6-digit UPC-E body to the 12-digit UPC-A (with check digit)."""
    d = six
    last = d[5]
    if last in "012":
        body = d[0:2] + last + "0000" + d[2:5]
    elif last == "3":
        body = d[0:3] + "00000" + d[3:5]
    elif last == "4":
        body = d[0:4] + "00000" + d[4]
    else:
        body = d[0:5] + "0000" + last
    body = number_system + body
    return body + str(gtin_check_digit(body))


def _local(raw: str, hint: str | None) -> NormalizedBarcode:
    return NormalizedBarcode(code=f"local:{raw}", raw=raw, symbology=hint or "other", valid=False)


def normalize(raw: str, symbology_hint: str | None = None) -> NormalizedBarcode:
    """Normalise a scanned value to a catalogue key.

    GTIN family with a valid check digit -> left-padded 14 digits. EAN-13 prefix 20-29
    (in-store/variable weight) -> ``instore:<first 7 digits>``. Anything else -> ``local:<raw>``.
    """
    stripped = raw.strip()
    if not stripped:
        raise ValueError("empty barcode")
    hint = symbology_hint if symbology_hint in SYMBOLOGIES else None
    if hint in NON_GTIN_SYMBOLOGIES:
        return _local(stripped, hint)

    digits = _WS.sub("", stripped)
    if not digits.isdigit():
        return _local(stripped, hint)

    n = len(digits)
    if n == 6 or (n == 8 and hint == "upc_e"):
        if n == 6:
            upc_a = expand_upc_e(digits, "0")
        else:
            if digits[0] not in "01":
                return _local(stripped, hint)
            upc_a = expand_upc_e(digits[1:7], digits[0])
            if upc_a[-1] != digits[7]:
                return _local(stripped, hint)
        return NormalizedBarcode(upc_a.rjust(14, "0"), stripped, "upc_e", True)

    kinds = {8: "ean_8", 12: "upc_a", 13: "ean_13", 14: "itf"}
    if n not in kinds or not has_valid_check_digit(digits):
        return _local(stripped, hint)

    if n == 13 and digits[:2] in {"20", "21", "22", "23", "24", "25", "26", "27", "28", "29"}:
        return NormalizedBarcode(f"instore:{digits[:7]}", stripped, "ean_13", True)

    return NormalizedBarcode(digits.rjust(14, "0"), stripped, kinds[n], True)
