from fastapi import APIRouter

from app.api.deps import ServicesDep
from app.api.docs import describe
from app.api.errors import ERROR_RESPONSES
from app.api.schemas.verify import VerifyRequest, VerifyResponse

router = APIRouter(prefix="/v1/verify", tags=["signing"], responses=ERROR_RESPONSES)

_VERIFY = """
Checks the `signature` of an offer or an order confirmation with the key in
`/.well-known/jwks.json`.

**Request:**

```json
{"jws": "eyJhbGciOiJFZERTQSIs...", "body": {"order_id": "o_1", "total_ex_vat": "1010.00"}}
```

A changed payload gives `valid: false`. A changed value in the shown body keeps the JWS
valid and gives `body_matches: false`.

**Auth:** none. Anyone may check a statement.
"""


@router.post("", description=describe(_VERIFY, VerifyResponse, VerifyRequest))
def verify(request: VerifyRequest, services: ServicesDep) -> VerifyResponse:
    return VerifyResponse.of(services.signer.verify(request.jws), request.body)
