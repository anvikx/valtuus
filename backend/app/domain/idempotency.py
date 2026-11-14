import hashlib
import json
from collections.abc import Mapping
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


def request_hash(operation: str, payload: Mapping[str, object]) -> str:
    """The operation is in the hash, so one key reused for another call is a conflict."""
    body = json.dumps({"operation": operation, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()
