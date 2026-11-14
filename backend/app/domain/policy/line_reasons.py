from dataclasses import replace

from app.domain.cart import CartLine
from app.domain.policy.engine import PolicyResult, strictest


def apply_line_reasons(lines: tuple[CartLine, ...], result: PolicyResult) -> tuple[CartLine, ...]:
    updated = []
    for line in lines:
        own = [reason for reason in result.reasons if reason.line_id == line.product_id]
        updated.append(
            replace(
                line,
                decision=strictest(reason.decision for reason in own),
                reason_codes=tuple(reason.reason_code for reason in own),
                reason_sentences=tuple(reason.sentence for reason in own),
            )
        )
    return tuple(updated)
