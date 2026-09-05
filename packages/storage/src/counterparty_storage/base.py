"""Declarative base and shared column conventions.

Importing this module must not open a network connection, a database
connection or a file: it only builds SQLAlchemy metadata.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import TIMESTAMP, MetaData, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

#: Deterministic constraint names keep migrations reviewable and reversible.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}

#: Reported amounts are stored exactly; float is never used for money.
MONEY = Numeric(20, 2)

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Common declarative base for every mapped table of the project."""

    metadata = metadata

    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy reads this as a plain dict
        datetime: TIMESTAMP(timezone=True),
        Decimal: MONEY,
        dict[str, Any]: JSONB,
    }
