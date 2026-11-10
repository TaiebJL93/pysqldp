"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from pysqldp.schema import Database, Schema

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden"

#: The privacy parameter the Scala smoke tests use, so noise scales line up
#: with the committed golden outputs.
EPSILON = 0.1


@pytest.fixture(scope="session")
def schema() -> Schema:
    """The schema file copied verbatim from the Scala project."""
    return Schema.load(FIXTURES / "schema.yaml")


@pytest.fixture(scope="session")
def experiments(schema: Schema) -> Database:
    """The ``experiments`` database the smoke-test queries run against."""
    return schema.database("experiments")


@pytest.fixture(scope="session")
def test_db(schema: Schema) -> Database:
    """The ``test`` database, which exercises namespaces and nested fields."""
    return schema.database("test")
