"""Provider-neutral interface for private proof objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class StoredObject:
    """Metadata returned after a blob is written."""

    key: str
    byte_size: int
    sha256: str


class BlobStorage(Protocol):
    """The small contract shared by local storage and a future OSS adapter."""

    def put(self, key: str, content: bytes) -> StoredObject:
        """Persist one object and return its content metadata."""
        ...

    def get(self, key: str) -> bytes:
        """Read one object by its private storage key."""
        ...

    def delete(self, key: str) -> None:
        """Delete one object, tolerating an already absent object."""
        ...


__all__ = ["BlobStorage", "StoredObject"]
