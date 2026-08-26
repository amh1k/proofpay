"""Errors raised by the proof upload and storage boundary."""

from __future__ import annotations


class UploadError(ValueError):
    """Base class for a rejected upload."""


class UploadTooLarge(UploadError):
    """The request body is larger than the configured upload limit."""


class UnsupportedImage(UploadError):
    """The bytes are not one of the image formats ProofPay accepts."""


class InvalidImage(UploadError):
    """The bytes claim to be an image but cannot be decoded safely."""


class StorageError(OSError):
    """The configured blob store could not persist or retrieve an object."""


__all__ = [
    "InvalidImage",
    "StorageError",
    "UnsupportedImage",
    "UploadError",
    "UploadTooLarge",
]
