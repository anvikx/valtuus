import pytest

from app.api.schemas.catalog import SearchRequest
from app.api.schemas.mandate import MandateUpdateRequest
from app.api.schemas.offers import OfferRequest


@pytest.mark.parametrize(
    ("model", "body"),
    [(SearchRequest, {"query": "milk"}), (OfferRequest, {"product_ids": ["464306"]})],
)
@pytest.mark.parametrize("preference", [{}, {"preferred_brands": []}])
def test_absent_brand_means_no_preference(model, body, preference):
    request = model.model_validate({**body, **preference})

    assert request.preferred_brands == []
    assert request.to_domain().preferred_brands == ()


def test_empty_list_clears_mandate():
    changes = MandateUpdateRequest.model_validate({"preferred_brands": []}).to_domain()

    assert changes.preferred_brands == ()


def test_omitted_brand_keeps_mandate():
    changes = MandateUpdateRequest.model_validate({}).to_domain()

    assert changes.preferred_brands is None
