## Background concepts

See the Chorus papers for reference on these concepts:

- _Sensitivity_
- _Domain tables_ and _bin filling_
- _Stability_
- _Clipping_

## Structure

See the types in `com.uber.engsec.dp.schema.Schema` for the normative type definitions.

* **Databases**, the root of the schema file
  * `databases`: array of `Database`.
* **Database**
  * `database`: string, the name of the database.
  * `dialect`: string, the Calcite SQL dialect to use when parsing and rewriting queries, e.g. `hive`.
    Not case sensitive.
    See `org.apache.calcite.sql.SqlDialect.DatabaseProduct` for available values.
  * `namespace`: string, causes the rewriter to refer to tables as `namespace.table`.
    Set to the empty string to use only `table`.
  * `tables`: array of `Table`.
* **Table**
  * `table`: string, the name of the table.
  * `columns`: array of `Column`.
* **Column**
  * `name`: string, the name of the column.
  * `typeName`: string, the type of the column, e.g. `DOUBLE`.
    Used in columns that undergo percentile aggregations.
    See `org.apache.calcite.sql.type.SqlTypeName` for available values.
    If not set, uses `ANY`.
  * `fields`: array of `Column`, the nested fields, for databases that support that.

## Additional fields

**Access control**

- `isPublic` boolean on tables, set to `true` to indicate that the entire table has no sensitive information.
- `canRelease`: boolean on columns, set to `true` to allow values from this column to show up in outputs, e.g. for
  columns used in `GROUP BY` clauses.
- `isTainted`: boolean on columns, set to `true` to find output columns that depend on this column using
  `TaintAnalysis`.

**Elastic sensitivity**

- `maxFreq`: double on columns, the maximum number of rows that can have the same value.
  Used on columns that are compared in an equi-join.
  When using `TruncatingRewriter`, it truncates to this frequency.
- `isPretruncated`: boolean on tables, set to `true` to indicate to `PretruncatedElasticSensitivityRewriter` that the
  table is already truncated to its columns' specified `maxFreq`s.
- `pretruncatedCopy`: string on tables, the name of a table that is a copy of this table that has been truncated to
  this table's columns' specified `maxFreq`s.
  When using `TruncatingRewriter`, it replaces a reference to this table with the table named here if one is available.
  Omit this field to have `TruncatingRewriter` output code to do the truncation on the fly.
- `truncateOrder`: string on tables, a comma-separated list of column names for `TruncatingRewriter` to truncate in
  sequence.
  Omitting this field is equivalent to truncating each column independently and then taking the intersection, which can
  be worse.

**Sample and aggregate**

- `approxRowCount`: long on tables, the approximate cardinality of table.
  See source code in `SampleAndAggregateRewriter` for details on this.

**Domain sets**

- `domainSet`: string on columns, the name of the table and column, e.g. `products.product_id`, containing the domain
  for this column.
- `useBreakdown` string on tables, the name of a special column for differentiating multiple domain sets stored in a
  single table.
  See source code in `DPUtil.constructDomainSet` for details on this.
  Omit this field to use the entire domain table without looking for such a column.
- `crossMarginal` boolean on columns, set to `true` to retrieve this column's domain set separately from other columns
  in a table with `useBreakdown`.
  See source code in `DPUtil.constructDomainSet` for details on this.

**Clipping**

- `clipLower`: double on columns, coerce values less than this to this value.
  Used in columns that undergo `SUM` or `AVG` aggregation.
- `clipUpper`: double on columns, coerce values greater than this to this value.
  Used in columns that undergo `SUM` or `AVG` aggregation.

**Percentile queries**

- `binsStart`: double on columns, the lower edge of the PDF/CDF bins to use.
  Used in columns that undergo percentile aggregation.
  If not set, uses the value from `clipLower`.
- `binsEnd`: double on columns, the higher edge of the PDF/CDF bins to use.
  Used in columns that undergo percentile aggregation.
  If not set, uses the value from `clipUpper`.
- `binsDistribution`: string on columns, how the bins are arranged between `binsStart` and `binsEnd`.
  Available values are `constant` and `exponential`.
  If not set, uses `constant`.
- `binsStep`: double on columns, when using `constant` `binsDistribution`, the size of each bin.
  If not set, uses 1/100th of `binsEnd - binsStart`.
- `percentError`: double on columns, when using `exponential` `binsDistribution`, the size of each bin relative to its
  lower edge, as a percentage, e.g. `1` for 1%, where a bin might cover `[20.0, 20.2)`.
  If not set, uses `1`.
