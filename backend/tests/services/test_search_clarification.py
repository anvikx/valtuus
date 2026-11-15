"""Search informs the agent of matches and missing facts without guessing buyer intent."""

from dataclasses import asdict

import pytest

from app.api.results import search_response
from app.config import Settings
from app.domain.enums import AuditStep, SearchHintCode
from tests.adapters.samples import agent_key
from tests.fakes.catalog import item, query, service
from tests.fakes.offer_data import FakeCatalog

_MAX_CANDIDATES = 40
_MISSING_FIELDS = ("quantity", "unit", "deliver_by")


@pytest.fixture
def configured_guard(monkeypatch):
    """Use the application's default, so a test-only limit cannot hide a production mismatch."""
    monkeypatch.delenv("CANDIDATE_GUARD", raising=False)
    return Settings(_env_file=None).candidate_guard


def _assert_one_search(records, result, offer_set_size=None):
    (record,) = records.records
    assert record.step is AuditStep.SEARCH
    assert record.phase == "LOOKUP"
    assert record.actor == agent_key().agent_id
    assert record.buyer_id == agent_key().buyer_id
    assert record.request_id == result.request_id
    assert record.cart_id is None
    assert record.decision is None
    assert record.input_data == asdict(result.understood)
    if offer_set_size is None:
        offer_set_size = len(result.candidates)
    assert record.output_data == {
        "candidate_ids": [candidate.product_id for candidate in result.candidates],
        "offer_set_size": offer_set_size,
        "hint_category": result.hint_category,
        "total_hits": result.total_hits,
        "hint": asdict(result.hint),
        "choices": [asdict(choice) for choice in result.choices],
    }


@pytest.mark.parametrize("hits", [39, 40, 41, 80])
def test_search_caps_candidates(hits, configured_guard):
    """The preview has at most 40 products while preserving the full match count."""
    products = [item(f"milk-{index:03}") for index in range(hits)]
    catalog, records = service(FakeCatalog(*reversed(products)), candidate_guard=configured_guard)

    result = catalog.search(agent_key(), query())

    _assert_one_search(records, result, offer_set_size=hits)
    assert result.total_hits == result.categories[0].hits == hits
    assert [candidate.product_id for candidate in result.candidates] == [
        product.product_id for product in products[:_MAX_CANDIDATES]
    ]
    # The stored set holds all hits (under the guard), so a cut preview hides nothing from offers.
    assert result.hint.code is SearchHintCode.READY
    assert result.hint.sentence


@pytest.mark.parametrize("guard", [1, 20, 40, 41, 500])
def test_search_guard_keeps_hard_cap(guard):
    """Configuration can narrow the preview, but cannot expand it beyond 40 candidates.

    Only a guard below the hit count cuts the stored set, so only it is GUARD_CUT.
    """
    catalog, records = service(
        FakeCatalog(*(item(f"milk-{index:03}") for index in range(41))),
        candidate_guard=guard,
    )

    result = catalog.search(agent_key(), query())

    _assert_one_search(records, result, offer_set_size=min(guard, 41))
    assert len(result.candidates) == min(guard, _MAX_CANDIDATES)
    assert result.total_hits == result.categories[0].hits == 41
    expected = SearchHintCode.GUARD_CUT if guard < 41 else SearchHintCode.READY
    assert result.hint.code is expected


@pytest.mark.parametrize("hits", [3, 41])
def test_vague_milk_search_only_informs(hits, configured_guard):
    """'Buy me milk' supplies product words, but no quantity, unit or delivery date."""
    catalog, records = service(
        FakeCatalog(*(item(f"milk-{index:03}") for index in range(hits))),
        candidate_guard=configured_guard,
    )
    request = query("milk", quantity=None, unit=None, deliver_by=None)

    result = catalog.search(agent_key(), request)

    _assert_one_search(records, result, offer_set_size=hits)
    assert result.understood == request
    assert result.missing_fields == _MISSING_FIELDS
    assert result.hint.code is SearchHintCode.MISSING_FIELDS
    assert "Ask the buyer" in result.hint.sentence
    assert result.total_hits == hits
    for candidate in result.candidates:
        assert candidate.sales_units_needed is None
        assert candidate.quantity_delivered is None
        assert candidate.quantity_over_request is None
    body = search_response(result).model_dump(mode="json")
    assert body["missing_fields"] == list(_MISSING_FIELDS)
    assert all("unit_price" not in candidate for candidate in body["candidates"])
    assert "cart_id" not in body
    assert "order_id" not in body
    assert len(result.candidates) == min(hits, _MAX_CANDIDATES)


@pytest.mark.parametrize(
    "missing",
    [
        ("quantity",),
        ("unit",),
        ("deliver_by",),
        ("quantity", "unit"),
        ("quantity", "deliver_by"),
        ("unit", "deliver_by"),
        _MISSING_FIELDS,
    ],
)
def test_search_names_all_missing_fields(missing):
    """The agent gets every missing field in one response, with supplied facts preserved."""
    catalog, records = service(FakeCatalog(item()))
    request = query(**dict.fromkeys(missing))

    result = catalog.search(agent_key(), request)

    _assert_one_search(records, result)
    assert result.understood == request
    assert result.missing_fields == missing
    assert result.hint.code is SearchHintCode.MISSING_FIELDS
    assert len(result.candidates) == 1
    assert search_response(result).missing_fields == list(missing)


@pytest.mark.parametrize("products", [(), (item(name="Butter"),)], ids=["empty", "unrelated"])
@pytest.mark.parametrize("missing", [(), _MISSING_FIELDS], ids=["complete", "vague"])
def test_no_match_has_one_audit_record(products, missing):
    """An unsuccessful search is still recorded once, even if buyer facts are also missing."""
    catalog, records = service(FakeCatalog(*products))
    request = query("milk", **dict.fromkeys(missing))

    result = catalog.search(agent_key(), request)

    _assert_one_search(records, result)
    assert result.hint.code is SearchHintCode.NO_MATCH
    assert result.hint.sentence == "No product matches. Try other words, or fewer words."
    assert result.total_hits == 0
    assert result.candidates == ()
    assert result.categories == ()
    assert result.excluded == ()
    assert result.missing_fields == missing
    assert result.request_id
