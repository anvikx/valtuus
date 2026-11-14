import hashlib
import hmac
import secrets
from datetime import timedelta

from app.domain.agent_key import User
from app.domain.errors import UnauthenticatedError
from app.domain.session import Session, hash_session_token
from app.services.ports.clock import Clock
from app.services.ports.repositories import SessionRepository, UserRepository
from app.services.ports.unit_of_work import UnitOfWork

# One working day. A stolen cookie stops working by the next morning.
SESSION_TTL = timedelta(hours=12)
_TOKEN_BYTES = 32
# scrypt makes each guess at the password from a leaked tag slow. The salt is fixed because
# there is one password, and each tag also mixes in its own token hash.
_TAG_KEY_SALT = b"valtuus-main-user-session"
_TAG_KEY_COST = 2**14


class SessionService:
    """Login sessions of the main user. They are stored, so a deploy does not log out."""

    def __init__(
        self,
        users: UserRepository,
        sessions: SessionRepository,
        clock: Clock,
        unit_of_work: UnitOfWork,
        main_user_id: str,
        main_user_password: str,
    ) -> None:
        # A blank password would let an empty login open the approve page.
        if not main_user_password.strip():
            raise ValueError("the main user password is empty")

        self._users = users
        self._sessions = sessions
        self._clock = clock
        self._unit_of_work = unit_of_work
        self._main_user_id = main_user_id
        self._password = main_user_password.encode()
        self._tag_key = hashlib.scrypt(
            self._password,
            salt=_TAG_KEY_SALT,
            n=_TAG_KEY_COST,
            r=8,
            p=1,
        )

    def login(self, password: str) -> str:
        """A new session token, or UnauthenticatedError for a wrong password."""
        # Constant time, so the response time does not leak how much of the password matched.
        if not hmac.compare_digest(password.encode(), self._password):
            raise UnauthenticatedError(
                "The password is wrong.",
                "Check the password and log in again.",
            )

        now = self._clock.now()
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        token_hash = hash_session_token(token)
        session = Session(
            token_hash,
            self._main_user_id,
            now + SESSION_TTL,
            self._password_tag(token_hash),
        )
        with self._unit_of_work.transaction():
            # Drop the sessions nobody logged out of, so the store does not grow for ever.
            self._sessions.remove_expired(now)
            self._sessions.add(session)

        return token

    def user_for(self, token: str) -> User | None:
        """The user of a live session, or None for a missing, unknown, expired or old token.

        Old means opened with a password that has since changed.
        """
        if not token:
            return None

        token_hash = hash_session_token(token)
        session = self._sessions.get(token_hash)
        if session is None or not session.is_live(self._clock.now()):
            return None

        if not hmac.compare_digest(session.password_tag, self._password_tag(token_hash)):
            return None

        return self._users.get(session.user_id)

    def _password_tag(self, token_hash: str) -> str:
        return hmac.new(self._tag_key, token_hash.encode(), hashlib.sha256).hexdigest()

    def logout(self, token: str) -> None:
        with self._unit_of_work.transaction():
            self._sessions.remove(hash_session_token(token))
