from decimal import Decimal

from app.adapters.catalog_enrichment import load_enrichment


def test_enrichment_keeps_precision_and_warns_on_bad_rows(tmp_path, caplog):
    path = tmp_path / "carbon.csv"
    path.write_text("productId,AVG kg CO2-eq/kg\n123,1.234567890123456789\n456,bad\n,3\n789,\n")

    result = load_enrichment(path, "AVG kg CO2-eq/kg")

    assert result == {"123": Decimal("1.234567890123456789")}
    assert "invalid AVG kg CO2-eq/kg for product 456" in caplog.text
    assert "missing productId" in caplog.text


def test_missing_enrichment_is_empty(tmp_path):
    assert load_enrichment(tmp_path / "missing.csv", "deliveryReliability") == {}
