import pytest

from pantrynanny.services.barcodes import expand_upc_e, gtin_check_digit, normalize


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
