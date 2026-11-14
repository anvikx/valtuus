from decimal import Decimal

import pytest

from app.domain.audit import audit_phase, policy_sentence
from app.domain.enums import AuditStep, Decision, FlowPhase
from app.domain.reason_text import money_text


@pytest.mark.parametrize(
    ("step", "phase"),
    [
        (AuditStep.SEARCH, FlowPhase.LOOKUP),
        (AuditStep.OFFER, FlowPhase.LOOKUP),
        (AuditStep.CART, FlowPhase.ORDER),
        (AuditStep.POLICY, FlowPhase.APPROVAL),
        (AuditStep.APPROVAL, FlowPhase.APPROVAL),
        (AuditStep.ORDER, FlowPhase.APPROVAL),
        (AuditStep.MANDATE_CHANGED, None),
        (AuditStep.AGENT_REVOKED, None),
    ],
)
def test_each_step_has_one_phase(step, phase):
    """The run page groups records by phase, so a step must always land in the same group."""
    assert audit_phase(step, cart_id="c_1") is phase


def test_refusal_is_in_a_phase_only_with_a_cart():
    """A refused call on a cart belongs to its approval; one without a cart is in no run."""
    assert audit_phase(AuditStep.REFUSED, cart_id="c_1") is FlowPhase.APPROVAL
    assert audit_phase(AuditStep.REFUSED, cart_id=None) is None


def test_money_text_groups_thousands():
    """The main user reads 1,010.00 EUR faster than 1010.00 EUR."""
    assert money_text(Decimal("1010.00")) == "1,010.00 EUR"
    assert money_text(Decimal("48.02")) == "48.02 EUR"


def test_money_text_rounds_half_up():
    """The text must show the same cents as the stored total, which rounds half up."""
    assert money_text(Decimal("0.125")) == "0.13 EUR"


@pytest.mark.parametrize(
    ("decision", "reasons", "sentence"),
    [
        pytest.param(
            Decision.HUMAN,
            ("1,010.00 EUR is over the 500.00 EUR limit.",),
            "The policy sent the cart to a person: 1,010.00 EUR is over the 500.00 EUR limit.",
            id="run-1",
        ),
        pytest.param(
            Decision.AUTO,
            (),
            "The policy let the agent order: the cart is within the mandate.",
            id="auto",
        ),
        pytest.param(
            Decision.DENY,
            ("A.", "B."),
            "The policy refused the cart: A. B.",
            id="every-reason",
        ),
    ],
)
def test_policy_sentence_says_the_outcome_then_why(decision, reasons, sentence):
    """The person reads the outcome first and every reason after it, in one line."""
    assert policy_sentence(decision, reasons) == sentence
