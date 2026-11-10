"""Schema loading and metadata lookup."""

from __future__ import annotations

import pytest

from pysqldp.schema import (
    Database,
    Schema,
    SchemaException,
    get_schema_map_for_table,
    get_table_properties,
)

from .conftest import FIXTURES


def test_loads_every_database_from_the_scala_fixture(schema: Schema) -> None:
    assert set(schema.database_names) >= {"test", "test2", "experiments"}


def test_dialect_maps_onto_sqlglot(experiments: Database, test_db: Database) -> None:
    assert experiments.dialect == "presto"
    assert experiments.sqlglot_dialect == "presto"
    # Calcite spells it "postgresql"; sqlglot spells it "postgres".
    assert Database(database="d", dialect="postgresql").sqlglot_dialect == "postgres"
    assert test_db.sqlglot_dialect == "hive"


def test_unknown_dialect_falls_back_to_generic() -> None:
    assert Database(database="d", dialect="exotic").sqlglot_dialect is None


def test_non_structural_keys_become_string_properties(experiments: Database) -> None:
    columns = get_schema_map_for_table(experiments, "table_b")

    # Numbers arrive as strings, mirroring Scala's Map[String, String].
    assert columns["ja1"].properties["maxFreq"] == "25"
    assert columns["ja1"].float_property("maxFreq") == 25.0
    assert columns["g1"].properties["domainSet"] == "g1_g2_domain.g1"


def test_booleans_are_lowercased_for_round_tripping(experiments: Database) -> None:
    columns = get_schema_map_for_table(experiments, "table_b")
    assert columns["g1"].properties["canRelease"] == "true"
    assert columns["g1"].bool_property("canRelease") is True
    assert columns["ja1"].bool_property("canRelease") is False


def test_table_level_properties_are_kept(experiments: Database) -> None:
    properties = get_table_properties(experiments, "table_a")
    assert properties["isPretruncated"] == "true"
    assert experiments.table("table_a").bool_property("isPretruncated") is True


def test_is_public_defaults_to_false(experiments: Database) -> None:
    assert experiments.table("table_b").is_public is False


def test_public_table_is_detected(schema: Schema) -> None:
    assert schema.database("test").table("products").is_public is True


def test_namespace_is_applied_when_qualifying(test_db: Database) -> None:
    assert test_db.namespace == "public"
    assert test_db.qualified("orders") == "public.orders"
    # Already-qualified names are left alone rather than doubled up.
    assert test_db.qualified("public.orders") == "public.orders"


def test_table_lookup_tolerates_the_namespace_prefix(test_db: Database) -> None:
    assert test_db.table("public.orders").table == "orders"
    assert test_db.table("orders").table == "orders"


def test_empty_namespace_leaves_names_bare(experiments: Database) -> None:
    assert experiments.namespace == ""
    assert experiments.qualified("table_b") == "table_b"


def test_nested_fields_are_parsed(schema: Schema) -> None:
    column = schema.database("test2").table("my_table").column("structured_col")
    assert [f.name for f in column.fields] == ["field1", "field2"]
    assert [f.name for f in column.fields[1].fields] == ["subfield1"]


def test_type_name_defaults_to_any(schema: Schema) -> None:
    columns = get_schema_map_for_table(schema.database("test"), "orders")
    assert columns["order_id"].type_name == "ANY"


def test_second_fixture_declares_clipping_bounds() -> None:
    database = Schema.load(FIXTURES / "schema_2.yaml").database("test")
    age = get_schema_map_for_table(database, "te_user")["age"]
    assert age.type_name == "DOUBLE"
    assert age.float_property("clipLower") == 0.0
    assert age.float_property("clipUpper") == 80.0


def test_missing_database_names_the_alternatives(schema: Schema) -> None:
    with pytest.raises(SchemaException, match="known databases"):
        schema.database("nope")


def test_missing_table_names_the_alternatives(experiments: Database) -> None:
    with pytest.raises(SchemaException, match="known tables"):
        experiments.table("nope")


def test_missing_column_names_the_alternatives(experiments: Database) -> None:
    with pytest.raises(SchemaException, match="known columns"):
        experiments.table("table_b").column("nope")


def test_rejects_yaml_without_databases_key() -> None:
    with pytest.raises(SchemaException, match="'databases' key"):
        Schema.loads("tables: []")


def test_rejects_table_without_a_name() -> None:
    with pytest.raises(SchemaException, match="missing 'table'"):
        Schema.loads("databases:\n- database: d\n  tables:\n  - columns: []\n")
