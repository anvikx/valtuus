from pydantic import Field

from app.api.schemas.common import RequestModel


class LoginRequest(RequestModel):
    password: str = Field(description="The main user password.")
