"""Shared SQLAlchemy declarative base and schema conventions."""

from __future__ import annotations

import datetime as dt
from typing import Any, ClassVar

from sqlalchemy import JSON, DateTime, MetaData, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSON_VARIANT = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Base class shared by every persistence model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[object, object]] = {
        str: String(255),
        dict[str, Any]: JSON_VARIANT,
        dt.datetime: DateTime(timezone=True),
    }
