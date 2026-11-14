from app.domain.enums import ReasonCode
from app.domain.reason_text import REASON_TEXT


def test_every_reason_code_has_a_sentence() -> None:
    # A code with no template makes the page, the agent and the audit fall back to a bare code.
    missing = set(ReasonCode) - REASON_TEXT.keys()

    assert not missing
