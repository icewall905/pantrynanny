import pytest

from pantrynanny.services.barcodes import STRIP_CHARS, expand_upc_e, gtin_check_digit, normalize


def test_ean13_valid():
    n = normalize("5701234567899")
    assert gtin_check_digit("570123456789") == 9
    assert n.valid and n.code == "05701234567899" and n.symbology == "ean_13"
    assert n.raw == "5701234567899"


def test_ean13_and_upca_collapse_to_same_code():
    upc = normalize("036000291452", "upc_a")
    ean = normalize("0036000291452")
    assert upc.code == ean.code == "00036000291452"
    assert upc.symbology == "upc_a" and ean.symbology == "ean_13"


def test_ean8():
    n = normalize("96385074")
    assert n.valid and n.code == "00000096385074" and n.symbology == "ean_8"


def test_gtin14():
    n = normalize("15701234567896")
    assert gtin_check_digit("1570123456789") == 6
    assert n.valid and n.code == "15701234567896" and n.symbology == "itf"


def test_whitespace_stripped():
    assert normalize("  5701234567899\n").code == "05701234567899"
    assert normalize("5 701234 567899").code == "05701234567899"


@pytest.mark.parametrize(
    ("six", "body"),
    [
        ("123450", "01200000345"),  # last digit 0-2: n d1 d2 d6 0000 d3 d4 d5
        ("123451", "01210000345"),
        ("123452", "01220000345"),
        ("123453", "01230000045"),  # 3: n d1 d2 d3 00000 d4 d5
        ("123454", "01234000005"),  # 4: n d1 d2 d3 d4 00000 d5
        ("123455", "01234500005"),  # 5-9: n d1..d5 0000 d6
        ("123459", "01234500009"),
    ],
)
def test_upce_expansion(six, body):
    assert expand_upc_e(six) == body + str(gtin_check_digit(body))


def test_upce_known_vector():
    # Widely published example: UPC-E 01234565 <-> UPC-A 012345000065
    assert expand_upc_e("123456") == "012345000065"


def test_upce_with_hint_eight_digits():
    n = normalize("01234565", "upc_e")
    assert n.valid and n.code == "00012345000065" and n.symbology == "upc_e"


def test_upce_eight_digits_bad_check_is_local():
    n = normalize("01234566", "upc_e")
    assert not n.valid and n.code == "local:01234566"


def test_eight_digits_without_hint_is_ean8_not_upce():
    assert normalize("96385074").symbology == "ean_8"


def test_six_digits_is_upce():
    n = normalize("123456")
    assert n.valid and n.code == "00012345000065"


def _with_check(body: str) -> str:
    return body + str(gtin_check_digit(body))


def test_instore_prefix_ignores_price_part():
    a = normalize(_with_check("201234500123"))
    b = normalize(_with_check("201234509999"))
    assert a.valid and a.code == b.code == "instore:2012345"
    assert normalize(_with_check("291234500123")).code == "instore:2912345"


def test_instore_invalid_checksum_is_local():
    good = _with_check("201234500123")
    bad = good[:-1] + str((int(good[-1]) + 1) % 10)
    n = normalize(bad)
    assert not n.valid and n.code == f"local:{bad}"


def test_prefix_30_is_regular_gtin():
    n = normalize(_with_check("301234500123"))
    assert n.valid and not n.code.startswith("instore:")


def test_invalid_checksum_is_local():
    n = normalize("5701234567893")
    assert not n.valid and n.code == "local:5701234567893" and n.raw == "5701234567893"


@pytest.mark.parametrize("hint", ["qr", "code_128", "code_39", "data_matrix"])
def test_non_gtin_symbologies_are_local(hint):
    n = normalize("5701234567899", hint)
    assert not n.valid and n.code == "local:5701234567899" and n.symbology == hint


def test_alphanumeric_is_local():
    n = normalize("ABC-123")
    assert n.code == "local:ABC-123" and not n.valid


def test_wrong_length_is_local():
    assert normalize("12345").code == "local:12345"
    assert normalize("123456789").code == "local:123456789"


def test_empty_rejected():
    with pytest.raises(ValueError):
        normalize("   ")


# Parity vectors for the web port (same rule: strip STRIP_CHARS at both ends, ASCII digits only).
@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("5701234567899", "05701234567899"),
        ("\t5701234567899\r\n", "05701234567899"),
        ("\x1d5701234567899\x1d", "05701234567899"),  # GS1 group separator
        ("\x1c\x1e\x1f5701234567899", "05701234567899"),
        ("\x855701234567899\xa0", "05701234567899"),  # NEL, NBSP
        ("﻿5701234567899", "05701234567899"),  # BOM
        ("\x0b\x0c 5701234567899 ", "05701234567899"),
        ("5 701234 567899", "05701234567899"),  # inner ASCII whitespace ignored
    ],
)
def test_strip_parity_vectors(raw, code):
    n = normalize(raw)
    assert n.code == code and n.valid and n.raw == raw.strip(STRIP_CHARS)


@pytest.mark.parametrize(
    "raw",
    [
        "570123456789²",  # superscript two: str.isdigit() is True, must not crash
        "٥٧٠١234567899",  # Arabic-Indic digits
        "5701234567899​",  # zero-width space is NOT stripped
        "57\xa001234567899",  # inner NBSP is not ignorable
        "57\x1d01234567899",  # inner separators are not ignorable
        "５701234567899",  # full-width digit
    ],
)
def test_non_ascii_digits_are_local_not_errors(raw):
    n = normalize(raw)
    assert not n.valid and n.code == f"local:{raw.strip(STRIP_CHARS)}"


@pytest.mark.parametrize("raw", ["", "  ", "\t\n", "\x1d\x1c", "\xa0﻿\x85"])
def test_blank_after_strip_rejected(raw):
    with pytest.raises(ValueError):
        normalize(raw)


@pytest.mark.parametrize(
    ("raw", "expected_code"),
    [
        # coordinator's cross-implementation vectors, with the valid check digit (9). The
        # "...892" spelling has a bad checksum and therefore parity-maps to local:<stripped>.
        ("5701234567899\x1d", "05701234567899"),
        ("\x1d5701234567899", "05701234567899"),
        ("﻿5701234567899", "05701234567899"),
        (" 5701234567899\u0085", "05701234567899"),
        ("570 1234 567899", "05701234567899"),
        ("​5701234567899", "local:​5701234567899"),
        ("570123456789²", "local:570123456789²"),
        ("5701234567892\x1d", "local:5701234567892"),
        ("５７０１２３４５６７８９９", "local:５７０１２３４５６７８９９"),
        ("٥٧٠١٢٣٤٥٦٧٨٩٩", "local:٥٧٠١٢٣٤٥٦٧٨٩٩"),
    ],
)
def test_cross_implementation_vectors(raw, expected_code):
    assert normalize(raw).code == expected_code
