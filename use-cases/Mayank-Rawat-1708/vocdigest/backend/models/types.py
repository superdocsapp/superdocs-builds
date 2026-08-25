"""
@file: backend/models/types.py
@description: Dialect-aware column types. The production database is Postgres with
    pgvector, but the test suite must run with no infrastructure at all. VectorType
    resolves to a real pgvector column on Postgres and to a JSON-encoded list on
    SQLite, so the same models work in both places without conditional code in the
    model definitions themselves.
@flow: SQLAlchemy asks the type for a dialect implementation -> load_dialect_impl picks
    pgvector.Vector on postgresql, TEXT elsewhere -> bind/result processors convert
    between Python lists and the stored representation.
@dependencies:
    - pgvector.sqlalchemy.Vector: the real implementation on Postgres
    - sqlalchemy.types.TypeDecorator: the dispatch mechanism
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import Float, Text
from sqlalchemy.types import TypeDecorator


class VectorType(TypeDecorator):
    """Embedding column that works on Postgres (pgvector) and SQLite (JSON text).

    Only Postgres gets real vector operations — SQLite storage exists so the test suite
    can exercise the full pipeline without a database server. Similarity search on
    SQLite is computed in Python by the caller rather than in SQL.
    """

    impl = Text
    cache_ok = True

    class Comparator(TypeDecorator.Comparator):
        """Exposes pgvector's distance operators through the decorator.

        A TypeDecorator does not inherit the wrapped type's comparators, so without
        this the operators silently disappear and `Theme.embedding.cosine_distance(v)`
        raises AttributeError at query-build time — invisible on SQLite, fatal on
        Postgres. Operators are emitted as raw SQL so no pgvector import is needed at
        class-definition time.
        """

        def cosine_distance(self, other):
            return self.op("<=>", return_type=Float)(other)

        def l2_distance(self, other):
            return self.op("<->", return_type=Float)(other)

        def max_inner_product(self, other):
            return self.op("<#>", return_type=Float)(other)

    comparator_factory = Comparator

    def __init__(self, dimensions: int, *args: Any, **kwargs: Any) -> None:
        self.dimensions = dimensions
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value  # pgvector handles the list natively
        return json.dumps(list(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return list(value)

    def process_literal_param(self, value, dialect):
        if value is None:
            return None
        # pgvector accepts the bracketed literal form for inline parameters.
        return "[" + ",".join(str(float(v)) for v in value) + "]"
