import json
import sys

from app.adapters.product_store import ProductStore
from app.commands.check_catalog import main

_load_catalog = ProductStore.load


def test_check_catalog_inspection_and_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ProductStore, "load", _load_catalog)
    product = {
        "id": "42",
        "category": "1",
        "salesUnit": "KG",
        "allowedLotSize": 1,
        "synkkaData": {"names": [{"language": "en", "value": "Example"}]},
    }
    path = tmp_path / "valio_products.json"
    path.write_text(json.dumps([product]))
    monkeypatch.setattr(sys, "argv", ["check", "--data-dir", str(tmp_path), "42"])

    assert main() == 0
    assert '"product_id": "42"' in capsys.readouterr().out

    path.write_text(json.dumps([{"id": "bad"}]))
    assert main() == 1
    assert "product 'bad'" in capsys.readouterr().err
