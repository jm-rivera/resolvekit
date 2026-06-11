"""Canonical SQLite schema for DataPack artifacts."""

SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS entities (
        entity_id TEXT PRIMARY KEY,
        entity_type TEXT NOT NULL,
        canonical_name TEXT NOT NULL,
        canonical_name_norm TEXT NOT NULL,
        valid_from TEXT,
        valid_until TEXT,
        attrs_json TEXT
    );

    CREATE TABLE IF NOT EXISTS names (
        entity_id TEXT NOT NULL,
        name_kind TEXT NOT NULL,
        value TEXT NOT NULL,
        value_norm TEXT NOT NULL,
        lang TEXT NOT NULL DEFAULT '',
        script TEXT NOT NULL DEFAULT '',
        is_preferred INTEGER DEFAULT 0,
        PRIMARY KEY (entity_id, name_kind, value_norm, lang, script),
        FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
    );

    CREATE TABLE IF NOT EXISTS codes (
        entity_id TEXT NOT NULL,
        system TEXT NOT NULL,
        value TEXT NOT NULL,
        value_norm TEXT NOT NULL,
        PRIMARY KEY (entity_id, system),
        FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
    );

    CREATE TABLE IF NOT EXISTS relations (
        entity_id TEXT NOT NULL,
        relation_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        valid_from TEXT,
        valid_until TEXT,
        PRIMARY KEY (entity_id, relation_type, target_id),
        FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
    );

    CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
    CREATE INDEX IF NOT EXISTS idx_codes_lookup ON codes(system, value_norm);
    CREATE INDEX IF NOT EXISTS idx_codes_value_norm ON codes(value_norm);
    CREATE INDEX IF NOT EXISTS idx_names_lookup ON names(value_norm, name_kind);
    CREATE INDEX IF NOT EXISTS idx_relations_entity ON relations(entity_id, relation_type);
    CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id, relation_type);

    CREATE VIRTUAL TABLE IF NOT EXISTS names_fts USING fts5(
        entity_id,
        value_norm,
        content='names',
        content_rowid='rowid',
        tokenize='unicode61 remove_diacritics 1'
    );
"""
