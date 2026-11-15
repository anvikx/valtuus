from dataclasses import replace
from decimal import Decimal

import pytest

from app.domain.enums import ReasonCode, SubstituteBasis
from app.domain.mandate import RankingWeights
from app.domain.offer import Candidate, SubstituteFor
from app.domain.ranking import rank_offer_lines
from tests.fakes.offer_data import MONDAY, PRICE_ONLY, price, product, query, stock

# Real data (15 Nov 2026): reliability and CO2 in kg CO2e/kg from the Valio Aimo files.
EILA = ("464306", "Valio Arki Eila 1 l", "1.0", "1.1")
ARLA_UHT = ("469363", "Arla Semi skimmed milkdrink 1 L UHT", None, "1.1")
ARLA_PRO = ("462845", "Arla Pro 1,8 kg Creme fraiche", "1.0", "1.93")
VALIO_YOGHURT = ("462718", "Valio Turkish cooking yoghurt 2 kg", "0.99", "1.93")
VALIO_A_PLUS = ("462970", "Valio A+ natural yoghurt and muesli 200 g", "0.995", "1.93")

RELIABILITY_ONLY = RankingWeights(price=0.0, reliability=1.0, co2=0.0)
CO2_ONLY = RankingWeights(price=0.0, reliability=0.0, co2=1.0)


def _candidate(data, unit_price: str, **stock_fields) -> Candidate:
    product_id, name, reliability, co2 = data
    item = replace(
        product(product_id),
        name=name,
        delivery_reliability=None if reliability is None else Decimal(reliability),
        co2_kg_per_kg=None if co2 is None else Decimal(co2),
    )
    return Candidate(item, price(product_id, unit_price), stock(product_id, **stock_fields))


def _ids(candidates, weights) -> list[str]:
    return [line.product_id for line in rank_offer_lines(candidates, query(), weights)]


def test_price_only_weights_keep_the_price_order_with_ties() -> None:
    """The seed weights are 1/0/0. Reliability and CO2 data must not move any line then."""
    candidates = [
        _candidate(VALIO_YOGHURT, "1.20"),
        _candidate(ARLA_UHT, "1.01"),
        _candidate(EILA, "1.01"),
        _candidate(ARLA_PRO, "0.95"),
        _candidate(VALIO_A_PLUS, "1.20"),
    ]

    # Price order, ties by product id: 462845, then 464306 before 469363, then 462718, 462970.
    assert _ids(candidates, PRICE_ONLY) == ["462845", "464306", "469363", "462718", "462970"]


def test_reliability_weight_lifts_the_more_reliable_line_inside_its_group() -> None:
    """A cheaper line with misses must give way when the buyer weighs reliability."""
    cheap = _candidate(VALIO_YOGHURT, "1.00")
    reliable = _candidate(EILA, "1.05")

    assert _ids([cheap, reliable], PRICE_ONLY) == ["462718", "464306"]
    assert _ids([cheap, reliable], RELIABILITY_ONLY) == ["464306", "462718"]


def test_a_weight_never_moves_a_line_across_a_delivery_group() -> None:
    """A late line must stay behind a full line however reliable and green it is."""
    late = _candidate(EILA, "9.00", available_date=MONDAY.replace(day=17))
    on_time = _candidate(VALIO_YOGHURT, "1.00")

    for weights in (PRICE_ONLY, RELIABILITY_ONLY, CO2_ONLY):
        assert _ids([late, on_time], weights) == ["462718", "464306"]


def test_missing_reliability_never_wins() -> None:
    """No data is the worst value, so a product with no figure cannot beat one with data."""
    unknown = _candidate(ARLA_UHT, "1.00")
    poor = _candidate(VALIO_YOGHURT, "1.00")

    assert _ids([unknown, poor], RELIABILITY_ONLY) == ["462718", "469363"]


def test_missing_co2_never_wins() -> None:
    """No CO2 figure scores at least 1 and never better than the dearest known value."""
    unknown = _candidate((EILA[0], EILA[1], EILA[2], None), "1.00")
    known = _candidate(ARLA_PRO, "1.00")

    assert _ids([unknown, known], CO2_ONLY) == ["462845", "464306"]


def test_co2_weight_prefers_the_lower_footprint() -> None:
    """The milk at 1.1 kg CO2e/kg beats the cheaper cream at 1.93 once CO2 counts."""
    cheap_cream = _candidate(ARLA_PRO, "0.90")
    milk = _candidate(EILA, "1.01")

    assert _ids([cheap_cream, milk], PRICE_ONLY) == ["462845", "464306"]
    assert _ids([cheap_cream, milk], CO2_ONLY) == ["464306", "462845"]


def test_equal_scores_fall_to_product_id() -> None:
    """The same data must give the same rank 1 on every call."""
    # Same price and same CO2, so the weights give both lines one score.
    candidates = [_candidate(ARLA_PRO, "1.00"), _candidate(VALIO_YOGHURT, "1.00")]

    assert _ids(candidates, RankingWeights(0.5, 0.0, 0.5)) == ["462718", "462845"]


def test_the_score_is_the_same_wherever_the_line_ends_up() -> None:
    """A cheaper late line scores below 0 but still ranks after the full lines."""
    late = _candidate(ARLA_PRO, "0.50", available_date=MONDAY.replace(day=17))
    a = _candidate(EILA, "1.00")
    b = _candidate(VALIO_YOGHURT, "1.10")

    # Base 1.00 from the full group: a scores 0, b 0.10 and the late line -0.50.
    assert _ids([late, a, b], PRICE_ONLY) == ["464306", "462718", "462845"]


@pytest.mark.parametrize("weights", [PRICE_ONLY, RankingWeights(0.5, 0.3, 0.2)])
def test_a_single_candidate_ranks_first(weights: RankingWeights) -> None:
    """One line is its own base, so its premium is 0."""
    assert _ids([_candidate(EILA, "1.01")], weights) == ["464306"]


# Synthetic reliability on real ids: a cheap line with misses and a dear line that delivers.
_MISSES = (EILA[0], EILA[1], "0.90", None)
_DELIVERS = (VALIO_YOGHURT[0], VALIO_YOGHURT[1], "0.99", None)
_OUTLIER = (ARLA_PRO[0], ARLA_PRO[1], "0.50", None)
_EQUAL_PRICE_AND_RELIABILITY = RankingWeights(price=1.0, reliability=1.0, co2=0.0)


def test_a_one_cent_gap_does_not_outweigh_nine_points_of_reliability() -> None:
    """Equal weights must mean equal say. Min-max made 1 cent count as 1.0 against 0.09."""
    candidates = [_candidate(_MISSES, "1.00"), _candidate(_DELIVERS, "1.01")]

    assert _ids(candidates, _EQUAL_PRICE_AND_RELIABILITY) == ["462718", "464306"]


def test_a_dearer_line_does_not_change_the_order_of_two_others() -> None:
    """A substitute or an outlier in the offer must not reorder the lines the buyer asked for."""
    pair = [_candidate(_MISSES, "1.00"), _candidate(_DELIVERS, "1.01")]
    with_outlier = [*pair, _candidate(_OUTLIER, "2.00")]

    order = _ids(pair, _EQUAL_PRICE_AND_RELIABILITY)
    order_with_outlier = [i for i in _ids(with_outlier, _EQUAL_PRICE_AND_RELIABILITY) if i in order]

    assert order_with_outlier == order


def test_a_zero_minimum_does_not_divide_by_zero() -> None:
    """A CO2 figure of 0 is the best value. Any footprint above it scores as bad as no data."""
    zero = _candidate((EILA[0], EILA[1], "1.0", "0"), "1.00")
    some = _candidate(ARLA_PRO, "1.00")

    assert _ids([some, zero], CO2_ONLY) == ["464306", "462845"]


def test_a_cheap_late_line_does_not_change_the_trade_off_between_full_lines() -> None:
    """A line that cannot arrive in time must not make price gaps count more for those that can.

    With the base 0.70 from the late line, 5 cents counted 0.071 and the 93 % line won.
    """
    misses = _candidate((EILA[0], EILA[1], "0.93", None), "1.00")
    delivers = _candidate(_DELIVERS, "1.05")
    cheap_late = _candidate(_OUTLIER, "0.70", available_date=MONDAY.replace(day=17))

    without_late = _ids([misses, delivers], _EQUAL_PRICE_AND_RELIABILITY)
    with_late = _ids([misses, delivers, cheap_late], _EQUAL_PRICE_AND_RELIABILITY)

    assert without_late == ["462718", "464306"]
    assert with_late == [*without_late, "462845"]


def test_the_base_falls_to_the_next_group_when_the_best_has_no_data() -> None:
    """No CO2 figure in the full group: the late line gives the base and the full lines tie."""
    dear = _candidate((EILA[0], EILA[1], "1.0", None), "1.10")
    cheap = _candidate((VALIO_YOGHURT[0], VALIO_YOGHURT[1], "1.0", None), "1.00")
    late = _candidate(ARLA_PRO, "1.00", available_date=MONDAY.replace(day=17))

    assert _ids([dear, cheap, late], CO2_ONLY) == ["462718", "464306", "462845"]


def test_a_cheap_substitute_does_not_set_the_price_base() -> None:
    """Base 1.00 ranks the reliable line first. A 0.50 base doubles the price gap and flips it."""
    cheap = ("p_cheap", "Cheap milk", "0.80", None)
    reliable = ("p_reliable", "Reliable milk", "0.99", None)
    swap = ("p_swap", "Swap milk", "0.99", None)
    marked = SubstituteFor(
        product_id="gone",
        name="Gone milk",
        basis=SubstituteBasis.VALIO_PAIR,
        reason_code=ReasonCode.NOT_AVAILABLE,
        reason_sentence="Valio Aimo cannot deliver this product.",
        price_difference_per_unit=None,
    )
    weights = RankingWeights(price=1.0, reliability=1.0, co2=0.0)

    lines = rank_offer_lines(
        [_candidate(cheap, "1.00"), _candidate(reliable, "1.10")],
        query(),
        weights,
        [(_candidate(swap, "0.50"), marked)],
    )

    assert [line.product_id for line in lines] == ["p_reliable", "p_cheap", "p_swap"]
