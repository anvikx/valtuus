from dataclasses import dataclass


@dataclass(frozen=True)
class IdempotencyRecord:
    """A retried call with the same key gets the first result, not a second cart or order.

    The same key with a different request_hash is a CONFLICT, not a replay.
    """

    buyer_id: str
    key: str
    request_hash: str
    result_id: str
