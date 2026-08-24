"""Reusable SQLAlchemy column annotations for ProofPay models."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from sqlalchemy import BigInteger, DateTime, Uuid, func
from sqlalchemy.orm import mapped_column

UuidPrimaryKey = Annotated[
    uuid.UUID,
    mapped_column(Uuid, primary_key=True, default=uuid.uuid4),
]
MoneyMinor = Annotated[
    int,
    mapped_column(BigInteger, nullable=False),
]
CreatedAt = Annotated[
    dt.datetime,
    mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False),
]
UpdatedAt = Annotated[
    dt.datetime,
    mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    ),
]

__all__ = ["CreatedAt", "MoneyMinor", "UpdatedAt", "UuidPrimaryKey"]
