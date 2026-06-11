"""SQLite package for builder schema, context, and operations."""

from resolvekit.builder.sqlite.context import attached_db, connect_sqlite, transaction
from resolvekit.builder.sqlite.diff import (
    TABLE_DIFF_SPECS,
    compute_table_diff,
    quote_identifier,
    sample_keys,
    table_count,
    write_domain_diffs,
)
from resolvekit.builder.sqlite.export import (
    build_symspell_dictionary,
    compute_selected_ids,
    copy_subset_to_datapack,
)
from resolvekit.builder.sqlite.validate import (
    REQUIRED_TABLES,
    validate_domain_db,
)
from resolvekit.builder.sqlite.write import (
    count_entities,
    count_missing_relation_targets,
    ensure_sqlite_schema,
    insert_normalized_payload,
    list_missing_relation_targets,
    rebuild_fts,
    staging_db_path,
)
from resolvekit.shared.build.schema import SCHEMA_SQL

__all__ = [
    "REQUIRED_TABLES",
    "SCHEMA_SQL",
    "TABLE_DIFF_SPECS",
    "attached_db",
    "build_symspell_dictionary",
    "compute_selected_ids",
    "compute_table_diff",
    "connect_sqlite",
    "copy_subset_to_datapack",
    "count_entities",
    "count_missing_relation_targets",
    "ensure_sqlite_schema",
    "insert_normalized_payload",
    "list_missing_relation_targets",
    "quote_identifier",
    "rebuild_fts",
    "sample_keys",
    "staging_db_path",
    "table_count",
    "transaction",
    "validate_domain_db",
    "write_domain_diffs",
]
