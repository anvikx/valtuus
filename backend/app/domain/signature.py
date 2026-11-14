import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

# The response field that carries the JWS. It is not part of the signed payload.
SIGNATURE_FIELD = "signature"


class VerifyFailure(StrEnum):
    MALFORMED = "MALFORMED"
    UNKNOWN_KEY = "UNKNOWN_KEY"
    BAD_SIGNATURE = "BAD_SIGNATURE"


@dataclass(frozen=True)
class Verified:
    kid: str
    payload: Mapping[str, object]


@dataclass(frozen=True)
class NotVerified:
    reason: VerifyFailure


Verification = Verified | NotVerified


def body_matches(payload: Mapping[str, object], body: Mapping[str, object]) -> bool:
    """The shown body says what was signed. Its own signature field is not part of the payload."""
    shown = {key: value for key, value in body.items() if key != SIGNATURE_FIELD}
    return _canonical(shown) == _canonical(payload)


def _canonical(value: Mapping[str, object]) -> str:
    # Python equality says True == 1 == 1.0. JSON text tells them apart, so a changed type fails.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
