"""Typed FastAPI dependencies shared across API versions."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from proofpay.db.session import get_session

SessionDep = Annotated[Session, Depends(get_session)]

__all__ = ["SessionDep"]
