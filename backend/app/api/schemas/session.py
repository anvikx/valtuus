from pydantic import BaseModel, Field

from app.api.schemas.common import RequestModel
from app.domain.enums import UserRole


class LoginRequest(RequestModel):
    password: str = Field(description="The main user password.")


class SessionUser(BaseModel):
    user_id: str = Field(description="The signed in user.")
    buyer_id: str | None = Field(description="The buyer the user acts for. null: staff.")
    role: UserRole = Field(description="What the user may do.")
