from fastapi import APIRouter

from app.api.deps import ServicesDep

router = APIRouter(tags=["signing"])


# Agents look the key up at this fixed root path (RFC 8615), so it stays outside /api.
@router.get("/.well-known/jwks.json")
def get_jwks(services: ServicesDep) -> dict[str, list[dict[str, str]]]:
    """Public keys that check the `signature` on offers and order confirmations (RFC 7517)."""
    return {"keys": [dict(key) for key in services.signer.public_keys()]}
