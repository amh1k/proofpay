"""Tests for the Track B upload validation and local proof storage boundary."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from proofpay.storage import (
    InvalidImage,
    LocalStorage,
    StorageError,
    UnsupportedImage,
    UploadTooLarge,
    validate_image,
)


def image_bytes(image_format: str) -> bytes:
    image = Image.new("RGB", (40, 20), (18, 92, 141))
    output = io.BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_validate_image_accepts_supported_formats(image_format: str) -> None:
    raw = image_bytes(image_format)

    upload = validate_image(raw, max_bytes=1_000_000)

    assert upload.original_media_type == {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }[image_format]
    assert upload.stored_media_type == "image/png"
    assert upload.original_size == len(raw)
    assert upload.stored_size == len(upload.stored_bytes)
    assert upload.width == 40
    assert upload.height == 20
    assert upload.storage_key == (
        f"proofs/{upload.original_sha256[:2]}/{upload.original_sha256}.png"
    )
    with Image.open(io.BytesIO(upload.stored_bytes)) as sanitised:
        assert sanitised.format == "PNG"
        assert sanitised.mode == "RGB"


def test_validate_image_rejects_bytes_that_only_claim_to_be_an_image() -> None:
    with pytest.raises(InvalidImage):
        validate_image(b"not an image", max_bytes=1_000_000)


def test_validate_image_rejects_unsupported_decodable_format() -> None:
    with pytest.raises(UnsupportedImage):
        validate_image(image_bytes("BMP"), max_bytes=1_000_000)


def test_validate_image_checks_size_before_decoding() -> None:
    with pytest.raises(UploadTooLarge):
        validate_image(b"x" * 11, max_bytes=10)


def test_local_storage_writes_and_reads_atomically(tmp_path) -> None:
    storage = LocalStorage(tmp_path)
    payload = b"sanitised proof bytes"

    stored = storage.put("proofs/ab/example.png", payload)

    assert stored.key == "proofs/ab/example.png"
    assert stored.byte_size == len(payload)
    assert storage.get(stored.key) == payload
    storage.delete(stored.key)
    with pytest.raises(StorageError):
        storage.get(stored.key)


@pytest.mark.parametrize("key", ["../escape", "/absolute", "proofs/../escape"])
def test_local_storage_rejects_path_traversal(tmp_path, key: str) -> None:
    storage = LocalStorage(tmp_path)

    with pytest.raises(StorageError):
        storage.put(key, b"private")
