"""Command-line interface.

Rewrites a query read from ``--query`` or stdin and prints the private SQL.
"""

from __future__ import annotations

import argparse
import sys

from .exceptions import DPException
from .pipeline import budget_usage, rewrite_fixed_pipeline
from .schema import Schema


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pysqldp",
        description=(
            "Rewrite a SQL query into a differentially private query that can "
            "run unchanged on any standard SQL engine."
        ),
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="path to the schema YAML file holding the privacy metadata",
    )
    parser.add_argument(
        "--database",
        required=True,
        help="name of the database within the schema file",
    )
    parser.add_argument(
        "--epsilon",
        type=float,
        default=0.1,
        help=(
            "privacy parameter; smaller means more noise and stronger privacy "
            "(default: %(default)s)"
        ),
    )
    parser.add_argument(
        "--query",
        help="the query to rewrite; omit to read it from stdin",
    )
    parser.add_argument(
        "--budget-only",
        action="store_true",
        help="print the privacy budget the query would spend, without rewriting",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="format the rewritten SQL across multiple lines",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    query = args.query if args.query is not None else sys.stdin.read()
    if not query.strip():
        print("error: no query given", file=sys.stderr)
        return 2

    if args.epsilon <= 0:
        print("error: --epsilon must be greater than zero", file=sys.stderr)
        return 2

    try:
        database = Schema.load(args.schema).database(args.database)

        if args.budget_only:
            print(budget_usage(database, query, args.epsilon))
            return 0

        sql, spent = rewrite_fixed_pipeline(database, query, args.epsilon)
    except DPException as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    except OSError as err:
        print(f"error: could not read schema: {err}", file=sys.stderr)
        return 1

    if args.pretty:
        import sqlglot

        sql = sqlglot.parse_one(sql, read=database.sqlglot_dialect).sql(
            dialect=database.sqlglot_dialect, pretty=True
        )

    print(sql)
    # Budget goes to stderr so stdout stays pipeable straight into a client.
    print(f"-- privacy budget spent: {spent}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
