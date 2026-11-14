import base64
import importlib.util
from dataclasses import asdict, replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.adapters.signer import Ed25519Signer
from app.api.results import order_response
from app.config import Settings
from app.main import create_app
from tests.adapters import samples

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rest_flow.py"
_SEED = bytes(range(32))
_ORDER = {
    "order_id": "o_1",
    "total_ex_vat": "1010.00",
}


def _load_script() -> ModuleType:
    # The script lives outside the backend package and runs with no install, so load it by path.
    spec = importlib.util.spec_from_file_location("rest_flow", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rest_flow = _load_script()


class _TestClientGateway:
    """The script's Gateway, but each call goes to an app with a real signing key."""

    def __init__(self, client: TestClient) -> None:
        self._client = client

    def anyone(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._client.request(method, f"/api/v1{path}", json=body)
        response.raise_for_status()
        return response.json()


@pytest.fixture
def gateway():
    settings = Settings(signing_private_key=SecretStr(base64.b64encode(_SEED).decode()))
    with TestClient(create_app(settings)) as client:
        yield _TestClientGateway(client)


def _signed(body: dict[str, str]) -> dict[str, str]:
    return {**body, "signature": Ed25519Signer(_SEED).sign(body)}


def test_signed_order_passes(gateway) -> None:
    rest_flow.check_signature(gateway, "order o_1", _signed(_ORDER))


def test_real_order_confirmation_passes(gateway) -> None:
    """Decimals and datetimes in the JSON body must compare equal to the signed payload."""
    order = samples.order()
    body = asdict(order)
    del body["signature"]
    signed = replace(order, signature=Ed25519Signer(_SEED).sign(body))
    shown = order_response(signed).model_dump(mode="json")

    rest_flow.check_signature(gateway, "order o_1", shown)


def test_changed_shown_total_fails(gateway) -> None:
    """The demo fallback must not pass a confirmation whose shown total was changed."""
    shown = {**_signed(_ORDER), "total_ex_vat": "1.00"}

    with pytest.raises(rest_flow.FlowError, match="differ"):
        rest_flow.check_signature(gateway, "order o_1", shown)


def test_signature_from_another_key_fails(gateway) -> None:
    other = Ed25519Signer(bytes(32)).sign(_ORDER)

    with pytest.raises(rest_flow.FlowError, match="not valid"):
        rest_flow.check_signature(gateway, "order o_1", {**_ORDER, "signature": other})


def test_missing_signature_fails(gateway) -> None:
    """Fail closed: a gateway with no signing key cannot pass the run."""
    with pytest.raises(rest_flow.FlowError, match="no signature"):
        rest_flow.check_signature(gateway, "order o_1", {**_ORDER, "signature": None})
