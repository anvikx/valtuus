from contextlib import AbstractContextManager
from typing import Protocol


class UnitOfWork(Protocol):
    def transaction(self) -> AbstractContextManager[None]:
        """A state change and its audit record are stored together or not at all."""
        ...
