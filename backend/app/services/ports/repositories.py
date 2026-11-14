from typing import Protocol

from app.domain.agent_key import AgentKey, User
from app.domain.mandate import Mandate


class MandateRepository(Protocol):
    def latest(self, buyer_id: str) -> Mandate | None: ...

    def add(self, mandate: Mandate) -> None:
        """Refuses a version that is not the next one, so no version is lost or overwritten."""
        ...


class AgentKeyRepository(Protocol):
    def by_hash(self, key_hash: str) -> AgentKey | None: ...

    def add(self, agent_key: AgentKey) -> None: ...


class UserRepository(Protocol):
    def get(self, user_id: str) -> User | None: ...

    def add(self, user: User) -> None: ...
