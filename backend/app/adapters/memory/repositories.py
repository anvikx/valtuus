import threading

from app.domain.agent_key import AgentKey, User
from app.domain.mandate import Mandate


class InMemoryMandateRepository:
    def __init__(self) -> None:
        self._versions: dict[str, list[Mandate]] = {}
        # Sync routes run in a thread pool; two edits must not both become version N.
        self._lock = threading.Lock()

    def latest(self, buyer_id: str) -> Mandate | None:
        versions = self._versions.get(buyer_id)
        return versions[-1] if versions else None

    def add(self, mandate: Mandate) -> None:
        with self._lock:
            versions = self._versions.setdefault(mandate.buyer_id, [])
            expected = len(versions) + 1
            if mandate.version != expected:
                raise ValueError(f"mandate version must be {expected}, got {mandate.version}")
            versions.append(mandate)


class InMemoryAgentKeyRepository:
    def __init__(self) -> None:
        self._by_hash: dict[str, AgentKey] = {}

    def by_hash(self, key_hash: str) -> AgentKey | None:
        return self._by_hash.get(key_hash)

    def add(self, agent_key: AgentKey) -> None:
        self._by_hash[agent_key.key_hash] = agent_key


class InMemoryUserRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, User] = {}

    def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    def add(self, user: User) -> None:
        self._by_id[user.user_id] = user
