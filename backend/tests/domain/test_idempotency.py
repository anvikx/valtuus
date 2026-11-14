from app.domain.idempotency import request_hash


def test_hash_ignores_key_order_but_not_values() -> None:
    """A retry from another client may order the JSON keys in another way."""
    first = request_hash("create_cart", {"a": 1, "b": [1, 2]})

    assert first == request_hash("create_cart", {"b": [1, 2], "a": 1})
    assert first != request_hash("create_cart", {"a": 2, "b": [1, 2]})


def test_hash_differs_by_operation() -> None:
    """One key used for a cart and then a checkout must not replay the cart."""
    assert request_hash("create_cart", {}) != request_hash("checkout", {})
