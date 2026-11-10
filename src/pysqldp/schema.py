"""Schema with differential-privacy metadata.

Port of ``com.uber.engsec.dp.schema.Schema`` / ``Database`` / ``Table`` /
``Column``. The YAML format is compatible with the Scala project's
``src/test/resources/schema.yaml``, so existing schema files load unchanged.

Only a handful of keys are structural (``database``, ``dialect``,
``namespace``, ``tables``, ``table``, ``columns``, ``name``, ``typeName``,
``fields``). Every other key is kept verbatim in ``properties`` as a string,
exactly like the Scala ``Map[String, String]``, because the rewriters look
metadata up by name at rewrite time. See ``docs/schema.md`` in the Scala repo
for the meaning of each property.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from .exceptions import DPException

# Keys consumed by the structure itself; everything else becomes a property.
_COLUMN_STRUCTURAL = frozenset({"name", "typeName", "fields"})
_TABLE_STRUCTURAL = frozenset({"table", "columns"})

# Calcite dialect name -> sqlglot dialect name.
_DIALECTS = {
    "hive": "hive",
    "presto": "presto",
    "trino": "trino",
    "postgresql": "postgres",
    "mysql": "mysql",
    "spark": "spark",
    "bigquery": "bigquery",
    "snowflake": "snowflake",
    "redshift": "redshift",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
}


class SchemaException(DPException):
    """The schema file is malformed, or a lookup missed."""


def _properties(raw: Mapping[str, Any], structural: frozenset[str]) -> dict[str, str]:
    """Collect non-structural keys as strings, mirroring Scala's Map[String, String]."""
    out: dict[str, str] = {}
    for key, value in raw.items():
        if key in structural:
            continue
        if isinstance(value, bool):
            # Scala reads these back with .toBoolean, which wants lowercase.
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


@dataclass(frozen=True)
class Column:
    """A column and its DP metadata."""

    name: str
    type_name: str = "ANY"
    fields: tuple[Column, ...] = ()
    properties: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Column:
        if "name" not in raw:
            raise SchemaException(f"column entry is missing 'name': {raw!r}")
        nested = tuple(Column.from_dict(f) for f in raw.get("fields") or ())
        return cls(
            name=raw["name"],
            type_name=raw.get("typeName", "ANY"),
            fields=nested,
            properties=_properties(raw, _COLUMN_STRUCTURAL),
        )

    def bool_property(self, key: str, default: bool = False) -> bool:
        value = self.properties.get(key)
        return default if value is None else value.strip().lower() == "true"

    def float_property(self, key: str) -> float | None:
        value = self.properties.get(key)
        return None if value is None else float(value)


@dataclass(frozen=True)
class Table:
    """A table, its columns, and table-level DP metadata."""

    table: str
    columns: tuple[Column, ...] = ()
    properties: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Table:
        if "table" not in raw:
            raise SchemaException(f"table entry is missing 'table': {raw!r}")
        return cls(
            table=raw["table"],
            columns=tuple(Column.from_dict(c) for c in raw.get("columns") or ()),
            properties=_properties(raw, _TABLE_STRUCTURAL),
        )

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def column(self, name: str) -> Column:
        for col in self.columns:
            if col.name == name:
                return col
        raise SchemaException(
            f"column {name!r} is not defined on table {self.table!r} "
            f"(known columns: {', '.join(self.column_names) or '<none>'})"
        )

    def bool_property(self, key: str, default: bool = False) -> bool:
        value = self.properties.get(key)
        return default if value is None else value.strip().lower() == "true"

    @property
    def is_public(self) -> bool:
        """True when the whole table holds no sensitive information."""
        return self.bool_property("isPublic")


@dataclass(frozen=True)
class Database:
    """One logical database: a dialect, a namespace, and its tables."""

    database: str
    dialect: str = "hive"
    namespace: str = ""
    tables: tuple[Table, ...] = ()

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Database:
        if "database" not in raw:
            raise SchemaException(f"database entry is missing 'database': {raw!r}")
        return cls(
            database=raw["database"],
            dialect=str(raw.get("dialect", "hive")).lower(),
            namespace=raw.get("namespace", "") or "",
            tables=tuple(Table.from_dict(t) for t in raw.get("tables") or ()),
        )

    @property
    def sqlglot_dialect(self) -> str | None:
        """sqlglot dialect name, or None for sqlglot's generic dialect."""
        return _DIALECTS.get(self.dialect)

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(t.table for t in self.tables)

    def table(self, name: str) -> Table:
        """Look a table up, tolerating a namespace prefix on either side.

        The rewriter refers to tables as ``namespace.table`` when a namespace is
        set, so a qualified name coming back from the IR has to resolve to the
        same unqualified schema entry.
        """
        for candidate in self._name_candidates(name):
            for table in self.tables:
                if table.table == candidate:
                    return table
        raise SchemaException(
            f"table {name!r} is not defined in database {self.database!r} "
            f"(known tables: {', '.join(self.table_names) or '<none>'})"
        )

    def has_table(self, name: str) -> bool:
        try:
            self.table(name)
        except SchemaException:
            return False
        return True

    def _name_candidates(self, name: str) -> list[str]:
        candidates = [name]
        prefix = f"{self.namespace}." if self.namespace else ""
        if prefix and name.startswith(prefix):
            candidates.append(name[len(prefix) :])
        if prefix:
            candidates.append(f"{prefix}{name}")
        return candidates

    def qualified(self, table_name: str) -> str:
        """Render a table reference the way the rewritten SQL should carry it."""
        if not self.namespace or table_name.startswith(f"{self.namespace}."):
            return table_name
        return f"{self.namespace}.{table_name}"


@dataclass(frozen=True)
class Schema:
    """The root of a schema file: a collection of databases."""

    databases: tuple[Database, ...] = ()

    @classmethod
    def loads(cls, text: str) -> Schema:
        raw = yaml.safe_load(text)
        if not isinstance(raw, Mapping) or "databases" not in raw:
            raise SchemaException("schema must be a mapping with a 'databases' key")
        return cls(tuple(Database.from_dict(d) for d in raw["databases"] or ()))

    @classmethod
    def load(cls, path: str | Path) -> Schema:
        return cls.loads(Path(path).read_text(encoding="utf-8"))

    @property
    def database_names(self) -> tuple[str, ...]:
        return tuple(d.database for d in self.databases)

    def database(self, name: str) -> Database:
        for db in self.databases:
            if db.database == name:
                return db
        raise SchemaException(
            f"database {name!r} is not defined "
            f"(known databases: {', '.join(self.database_names) or '<none>'})"
        )


# --- Free functions mirroring the Scala `Schema` object's API ----------------


def get_table_properties(database: Database, table_name: str) -> Mapping[str, str]:
    """Port of ``Schema.getTableProperties``."""
    return database.table(table_name).properties


def get_schema_map_for_table(database: Database, table_name: str) -> dict[str, Column]:
    """Port of ``Schema.getSchemaMapForTable``: column name -> column."""
    return {col.name: col for col in database.table(table_name).columns}
