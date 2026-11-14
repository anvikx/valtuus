from fastapi import APIRouter

router = APIRouter()


# The container health check and the deploy.sh rollback call this path. Do not move it.
@router.get("/health")
def get_health() -> dict[str, str]:
    return {"status": "ok"}
