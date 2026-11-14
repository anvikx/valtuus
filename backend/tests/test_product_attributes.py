import pytest

from app.domain.product_attributes import is_uht


@pytest.mark.parametrize(
    "names",
    [
        pytest.param(
            [
                "Valio Eila® semi skimmed milk drink 1 l UHT lactose free",
                "Valio Eila® kevytmaitojuoma 1 l UHT laktoositon",
                "Valio Eila® lättmjölkdryck 1 l UHT laktosfri",
            ],
            id="all-languages",
        ),
        pytest.param(
            [
                "10 x Cocio 1L crushed Ice Vanilla Milkdrink",
                "10 x Cocio 1L UHT crused Ice Vanilja maitojuoma",
                "10 x Cocio 1L UHT Crushed ice Vanilj mjölkdryck",
            ],
            id="missing-in-english",
        ),
        pytest.param(
            ["Arla Whole milk 1 L Suomesta low lactose Uht"],
            id="mixed-case",
        ),
    ],
)
def test_uht_in_any_name_marks_product_uht(names):
    """A mandate that requires UHT must find every UHT product, in any language or case."""
    is_product_uht = is_uht(names)

    assert is_product_uht


@pytest.mark.parametrize(
    "names",
    [
        pytest.param(
            [
                "10x Huhtamaki 100x116mm paper spoon kraft",
                "10x Huhtamaki 100x116mm paperilusikka kraft",
            ],
            id="uht-inside-word",
        ),
        pytest.param(
            ["Valio semi skimmed milk 1 l lactose free"],
            id="no-uht",
        ),
        pytest.param([], id="no-names"),
    ],
)
def test_no_uht_word_keeps_product_not_uht(names):
    """A non UHT product offered as UHT would break the buyer's required attribute."""
    is_product_uht = is_uht(names)

    assert not is_product_uht
