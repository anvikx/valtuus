import hashlib
from dataclasses import dataclass
from datetime import datetime


def hash_session_token(token: str) -> str:
    # Only the hash is stored, so a leaked table gives no working session. The token is long
    # and random, so a fast hash is safe.
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Session:
    token_hash: str
    user_id: str
    expires_at: datetime
    # Ties the session to the password it was opened with, so a new password ends it.
    password_tag: str

    def is_live(self, now: datetime) -> bool:
        return now < self.expires_at
