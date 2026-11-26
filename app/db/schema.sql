-- XBRL Agent v2 database. Applied on every start-up; every statement is
-- idempotent. A change an older database needs beyond a new table is made in
-- app/db/__init__.py (init_db).
-- Times are ISO 8601 UTC text ("2026-11-18T09:00:00Z").

-- People ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    email                TEXT PRIMARY KEY,               -- lower-cased login identity
    name                 TEXT NOT NULL DEFAULT '',
    password_hash        TEXT,                           -- argon2id
    is_admin             INTEGER NOT NULL DEFAULT 0,
    disabled             INTEGER NOT NULL DEFAULT 0,
    must_change_password INTEGER NOT NULL DEFAULT 0,     -- admin-issued temporary password
    created_at           TEXT NOT NULL,
    password_set_at      TEXT,
    last_sign_in_at      TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,                       -- random 256-bit token (hex)
    email        TEXT NOT NULL REFERENCES users(email) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL                           -- drives the sliding idle timeout
);
CREATE INDEX IF NOT EXISTS ix_sessions_email ON sessions(email);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    actor_email TEXT NOT NULL,                           -- text, not a key: outlives the account
    action      TEXT NOT NULL,
    target      TEXT NOT NULL,
    detail_json TEXT
);

-- Settings -------------------------------------------------------------

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);

-- Companies and runs ---------------------------------------------------

CREATE TABLE IF NOT EXISTS companies (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

-- A run made from an upload starts in 'reading' with no company, standard or
-- level: the Reader suggests them and the person confirms them at setup.
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER REFERENCES companies(id),
    year        INTEGER,
    standard    TEXT CHECK (standard IN ('MFRS', 'MPERS')),
    level       TEXT CHECK (level IN ('Company', 'Group')),
    -- 'ready': setup is confirmed and the run waits for extraction (step 3c).
    -- 'needs_answer': the figures agent asked a scope question and waits for a person (step 5b).
    status      TEXT NOT NULL DEFAULT 'reading' CHECK (status IN (
                    'reading', 'setup', 'ready', 'extracting', 'needs_answer', 'in_review', 'correcting',
                    'filed', 'failed', 'stopped')),
    owner_email TEXT NOT NULL REFERENCES users(email),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_updated ON runs(updated_at);

CREATE TABLE IF NOT EXISTS stages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    -- 'asking': the stage stopped to ask a person a scope question (step 5b).
    status      TEXT NOT NULL DEFAULT 'waiting' CHECK (status IN (
                    'waiting', 'working', 'asking', 'done', 'failed', 'stopped')),
    started_at  TEXT,
    finished_at TEXT,
    error       TEXT,
    working_on  TEXT,                                    -- the statement the stage is on now, or NULL (step 5c)
    stop_requested INTEGER NOT NULL DEFAULT 0,           -- 1: a person asked the stage to stop (step 5c)
    UNIQUE (run_id, name)
);

-- The job queue. A job is claimed by the one worker loop.
-- status: queued -> working -> done
--                            -> retry (failed, will run again) -> working ...
--                            -> failed (no attempts left)
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,                          -- the registered handler name
    payload_json TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'queued' CHECK (status IN (
                     'queued', 'working', 'retry', 'done', 'failed')),
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    run_after    TEXT NOT NULL,                          -- not claimed before this time
    last_error   TEXT,
    run_id       INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    stage_id     INTEGER REFERENCES stages(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_claim ON jobs(status, run_after);
-- Deleting a run deletes its jobs, and each deleted job clears events.job_id: both need these.
CREATE INDEX IF NOT EXISTS ix_jobs_run ON jobs(run_id);

-- Progress rows. The browser asks for "events after id N".
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    job_id     INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    source     TEXT NOT NULL,                            -- e.g. the agent's name
    kind       TEXT NOT NULL,                            -- e.g. step, tool, code, finished
    message    TEXT NOT NULL,
    data_json  TEXT,
    pages_json TEXT,                                     -- the PDF pages the step concerns, e.g. [7, 8] (step 5c)
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_run ON events(run_id, id);
CREATE INDEX IF NOT EXISTS ix_events_job ON events(job_id);

-- The document --------------------------------------------------------
-- One uploaded PDF per run, kept in the run's folder (app/documents/store.py).

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL UNIQUE REFERENCES runs(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,                           -- as uploaded, for display
    stored_path TEXT NOT NULL,                           -- relative to the output folder
    sha256      TEXT NOT NULL,
    size_bytes  INTEGER NOT NULL,
    page_count  INTEGER NOT NULL,
    uploaded_by TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    -- A run may start from a Word or Excel file (go-live plan C6). stored_path and page_count are then
    -- the reading copy the server laid out; filename, sha256 and size_bytes stay the uploaded file's.
    kind        TEXT NOT NULL DEFAULT 'pdf' CHECK (kind IN ('pdf', 'word', 'excel')),
    source_path TEXT,                                    -- the uploaded Word or Excel file; null for a PDF
    source_json TEXT                                     -- Excel: its sheets (app/documents/workbook_copy.py)
);

-- The words and numbers of a Word or Excel file exactly as the file holds them, one row per heading,
-- paragraph or table row, with the reading-copy page it is laid out on (app/documents/file_lines.py).
CREATE TABLE IF NOT EXISTS file_lines (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,                        -- order in the file, from 0
    page        INTEGER NOT NULL,                        -- reading-copy page, from 1
    kind        TEXT NOT NULL CHECK (kind IN ('heading', 'text', 'row')),
    block       INTEGER NOT NULL DEFAULT 0,              -- Word: the table's number, from 1; 0 outside a table
    sheet       TEXT,                                    -- Excel: the sheet's name
    row         INTEGER,                                 -- the row in its table (Word) or on its sheet (Excel)
    cells_json  TEXT NOT NULL,                           -- Word: the texts. Excel: [column, shown, saved value]
    PRIMARY KEY (document_id, position)
);
CREATE INDEX IF NOT EXISTS ix_file_lines_page ON file_lines(document_id, page);

-- One row per PDF page, written at upload. The Reader (step 3b) fills
-- content_json with the page's structured text.
CREATE TABLE IF NOT EXISTS pages (
    document_id    INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page           INTEGER NOT NULL,                     -- PDF page number, from 1
    width          REAL NOT NULL,                        -- points, after the page's rotation
    height         REAL NOT NULL,
    rotation       INTEGER NOT NULL DEFAULT 0,           -- as stored in the PDF: 0, 90, 180, 270
    has_text_layer INTEGER NOT NULL,                     -- decided per page (app/documents/pdf_check.py)
    content_json   TEXT,                                 -- the page's structured text (app/reading/content.py); null until read
    read_at        TEXT,
    read_error     TEXT,                                 -- a plain sentence when the page could not be read
    PRIMARY KEY (document_id, page)
);

-- The Reader's document map (docs/api-contract.md, "Reading"). Replaced on
-- every save; open_points_json holds the save tool's last unanswered points.
CREATE TABLE IF NOT EXISTS document_maps (
    run_id           INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    map_json         TEXT NOT NULL,
    open_points_json TEXT NOT NULL DEFAULT '[]',
    saved_at         TEXT NOT NULL
);

-- Every model call, failed ones included: tokens, an estimated cost, its
-- duration and any error (app/models/usage.py).
CREATE TABLE IF NOT EXISTS model_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER REFERENCES runs(id) ON DELETE CASCADE,
    source        TEXT NOT NULL,                         -- e.g. transcription, reader
    page          INTEGER,                               -- the PDF page, for a page's transcription
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,                      -- all input, cached included
    cached_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,                      -- reasoning included
    cost_usd      REAL,                                  -- null when the model's price is not known
    duration_ms   INTEGER,                               -- how long the call took, when measured
    error         TEXT,                                  -- the full error of a failed call (never shown to people)
    created_at    TEXT NOT NULL,
    agent         TEXT                                   -- the agent run as a person names it, e.g. "Placing the notes" (run cost)
);
CREATE INDEX IF NOT EXISTS ix_model_calls_run ON model_calls(run_id);

-- Template catalogue --------------------------------------------------
-- Rebuilt from the template files when they change (app/catalog/loader.py).
-- Columns copied from v1's db/schema.py so v1's queries and IDs carry over.

CREATE TABLE IF NOT EXISTS concept_templates (
    template_id   TEXT PRIMARY KEY,                      -- e.g. mfrs-company-sofp-cunoncu-v1
    source_path   TEXT NOT NULL,
    imported_at   TEXT,
    shape         TEXT NOT NULL DEFAULT 'linear'         -- 'linear' | 'matrix' (SOCIE)
);

-- One row per template line. Never deleted: a line that disappears from a
-- template is retired (is_current = 0) so saved figures keep their link.
CREATE TABLE IF NOT EXISTS concept_nodes (
    concept_uuid     TEXT PRIMARY KEY,                   -- UUID5 of template, sheet, row, label
    template_id      TEXT NOT NULL REFERENCES concept_templates(template_id) ON DELETE CASCADE,
    parent_uuid      TEXT REFERENCES concept_nodes(concept_uuid) ON DELETE SET NULL,
    kind             TEXT NOT NULL,                      -- ABSTRACT | LEAF | COMPUTED | MATRIX_CELL
    canonical_label  TEXT NOT NULL,
    display_label    TEXT,
    render_sheet     TEXT NOT NULL,
    render_row       INTEGER NOT NULL,
    render_col       TEXT NOT NULL,
    matrix_col       TEXT,                               -- SOCIE equity-component column letter
    matrix_col_label TEXT,                               -- SOCIE component header
    is_current       INTEGER NOT NULL DEFAULT 1,
    retired_at       TEXT
);
CREATE INDEX IF NOT EXISTS ix_concept_nodes_template ON concept_nodes(template_id, is_current);

-- The official SSM field name (taxonomy element) and fixed categories.
CREATE TABLE IF NOT EXISTS concept_semantic_addresses (
    concept_uuid      TEXT PRIMARY KEY REFERENCES concept_nodes(concept_uuid) ON DELETE CASCADE,
    primary_concept   TEXT NOT NULL,
    dimensions_json   TEXT NOT NULL DEFAULT '{}',
    taxonomy_version  TEXT NOT NULL DEFAULT '',
    address_version   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS taxonomy_concepts (
    source_element_id   TEXT PRIMARY KEY,
    taxonomy_version    TEXT NOT NULL,
    namespace_uri       TEXT NOT NULL,
    local_name          TEXT NOT NULL,
    abstract            INTEGER NOT NULL DEFAULT 0,
    concept_role        TEXT NOT NULL,
    data_type           TEXT,
    period_type         TEXT,
    balance             TEXT,
    substitution_group  TEXT
);

-- Every physical cell of each template and whether it can be written.
CREATE TABLE IF NOT EXISTS template_slots (
    target_id             TEXT PRIMARY KEY,
    canonical_target_id   TEXT NOT NULL,                 -- the concept_uuid
    template_id           TEXT NOT NULL,
    sheet                 TEXT NOT NULL,
    row                   INTEGER NOT NULL,
    col                   TEXT NOT NULL DEFAULT '',
    label                 TEXT NOT NULL,
    slot_role             TEXT NOT NULL,                 -- INPUT | FORMULA | MATRIX_* | PRESENTATION_ONLY | UNMAPPED
    value_kind            TEXT NOT NULL,                 -- numeric | html
    taxonomy_element_id   TEXT REFERENCES taxonomy_concepts(source_element_id),
    dimensions_json       TEXT NOT NULL DEFAULT '{}',
    mapping_source        TEXT NOT NULL,
    manifest_version      TEXT NOT NULL,
    workbook_fingerprint  TEXT NOT NULL,
    validation_status     TEXT NOT NULL,                 -- writable | non_writable | unresolved
    exception_code        TEXT,
    UNIQUE(template_id, sheet, row, col)
);
CREATE INDEX IF NOT EXISTS ix_template_slots_concept ON template_slots(canonical_target_id);

CREATE TABLE IF NOT EXISTS template_manifest_exceptions (
    template_id           TEXT NOT NULL,
    exception_code        TEXT NOT NULL,
    manifest_version      TEXT NOT NULL,
    workbook_fingerprint  TEXT NOT NULL,
    PRIMARY KEY(template_id, exception_code)
);

-- The sums: a total is the signed sum of its children.
CREATE TABLE IF NOT EXISTS concept_edges (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_uuid  TEXT NOT NULL REFERENCES concept_nodes(concept_uuid) ON DELETE CASCADE,
    child_uuid   TEXT NOT NULL REFERENCES concept_nodes(concept_uuid) ON DELETE CASCADE,
    coefficient  REAL NOT NULL DEFAULT 1.0,
    UNIQUE(parent_uuid, child_uuid)
);

-- The cell for each concept, entity and period.
CREATE TABLE IF NOT EXISTS concept_targets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_uuid  TEXT NOT NULL REFERENCES concept_nodes(concept_uuid) ON DELETE CASCADE,
    entity_scope  TEXT NOT NULL,                         -- Company | Group
    period        TEXT NOT NULL,                         -- CY | PY
    target_sheet  TEXT NOT NULL,
    target_row    INTEGER NOT NULL,
    target_col    TEXT NOT NULL,
    UNIQUE(concept_uuid, entity_scope, period)
);

-- A second cell for a concept that shows on two sheets (a face line fed by a sub-sheet total).
CREATE TABLE IF NOT EXISTS concept_render_aliases (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_uuid  TEXT NOT NULL REFERENCES concept_nodes(concept_uuid) ON DELETE CASCADE,
    alias_sheet   TEXT NOT NULL,
    alias_row     INTEGER NOT NULL,
    alias_col     TEXT NOT NULL,
    UNIQUE(concept_uuid, alias_sheet, alias_row, alias_col)
);

-- Rows of the prose-note templates. Filled from step 6.
CREATE TABLE IF NOT EXISTS notes_nodes (
    node_uuid           TEXT PRIMARY KEY,
    template_id         TEXT NOT NULL,
    sheet               TEXT NOT NULL,
    row                 INTEGER NOT NULL,
    label               TEXT NOT NULL,
    kind                TEXT NOT NULL,                   -- ABSTRACT | LEAF
    xbrl_concept_id     TEXT,
    slot_role           TEXT NOT NULL DEFAULT 'UNMAPPED',
    taxonomy_element_id TEXT,
    manifest_version    TEXT,
    UNIQUE(template_id, sheet, row)
);

-- v2 only: what the catalogue was built from, so an unchanged start-up skips the rebuild.
CREATE TABLE IF NOT EXISTS catalogue_sources (
    template_id  TEXT PRIMARY KEY,
    source_path  TEXT NOT NULL,                          -- relative to the project folder
    sha256       TEXT NOT NULL,
    built_with   TEXT NOT NULL,                          -- loader version + taxonomy fingerprint
    built_at     TEXT NOT NULL
);

-- Run setup ------------------------------------------------------------

-- Facts about a run the figure rules need. One row per run.
CREATE TABLE IF NOT EXISTS run_setup (
    run_id            INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    first_statements  INTEGER NOT NULL DEFAULT 0,        -- 1: first financial statements, no prior year
    unit              TEXT NOT NULL DEFAULT 'RM',        -- the report's unit, as printed (RM, RM'000)
    year_end          TEXT,                              -- YYYY-MM-DD, confirmed at setup
    notes_included    INTEGER NOT NULL DEFAULT 1         -- 0: the person switched the notes off at setup
);

-- The confirmed layout of each statement in a run.
CREATE TABLE IF NOT EXISTS run_statements (
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    statement  TEXT NOT NULL CHECK (statement IN ('SOFP', 'SOPL', 'SOCI', 'SOCF', 'SOCIE')),
    variant    TEXT NOT NULL,                            -- e.g. CuNonCu, Function, Indirect, Default, SoRE
    included   INTEGER NOT NULL DEFAULT 1,               -- 0: switched off at setup; no template is used
    pages_json TEXT NOT NULL DEFAULT '[]',               -- the PDF pages confirmed at setup, e.g. [13, 14]
    PRIMARY KEY (run_id, statement)
);

-- The notes list as the person confirmed it at setup (step 3c), in order.
CREATE TABLE IF NOT EXISTS run_notes (
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    position    INTEGER NOT NULL,                        -- order in the list, from 0
    number      TEXT NOT NULL,                           -- as printed, or '' when unreadable
    title       TEXT NOT NULL,
    first_page  INTEGER NOT NULL,                        -- PDF pages
    last_page   INTEGER NOT NULL,
    PRIMARY KEY (run_id, position)
);

-- Figures --------------------------------------------------------------
-- Every read and write goes through app/figures/store.py.

CREATE TABLE IF NOT EXISTS figures (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    concept_uuid     TEXT NOT NULL REFERENCES concept_nodes(concept_uuid),
    period           TEXT NOT NULL CHECK (period IN ('CY', 'PY')),
    entity_scope     TEXT NOT NULL CHECK (entity_scope IN ('Company', 'Group')),
    dimension_key    TEXT NOT NULL DEFAULT '',           -- category, as v1's sorted JSON, or ''
    value            REAL,                               -- blank means missing, never zero
    status           TEXT NOT NULL CHECK (status IN (
                         'observed', 'explicit_zero', 'not_disclosed', 'user_override')),
    children_status  TEXT CHECK (children_status IN ('itemised', 'aggregate_only')),
    origin           TEXT NOT NULL CHECK (origin IN (
                         'agent', 'person', 'calculated', 'prior_workbook', 'typed_in_workbook')),
    stated_value     REAL,                               -- a total as the report prints it
    locked           INTEGER NOT NULL DEFAULT 0,         -- 1: imported from last year's workbook
    certainty        TEXT NOT NULL DEFAULT 'sure' CHECK (certainty IN ('sure', 'unsure')),
    reason           TEXT NOT NULL DEFAULT '',           -- one line from the agent or person
    sign_question    INTEGER NOT NULL DEFAULT 0,         -- 1: open sign-only difference with last year
    source_ref       TEXT,                               -- imported: workbook hash, sheet, cell
    person_edited    INTEGER NOT NULL DEFAULT 0,         -- 1: a person changed it
    revision         INTEGER NOT NULL DEFAULT 1,
    updated_by       TEXT NOT NULL DEFAULT '',
    updated_at       TEXT NOT NULL,
    UNIQUE (run_id, concept_uuid, period, entity_scope, dimension_key)
);
CREATE INDEX IF NOT EXISTS ix_figures_run ON figures(run_id);

-- The printed lines behind a figure. One figure can add up several lines.
CREATE TABLE IF NOT EXISTS figure_lines (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    figure_id      INTEGER NOT NULL REFERENCES figures(id) ON DELETE CASCADE,
    printed_label  TEXT NOT NULL,                        -- the line as the report prints it
    print_order    INTEGER NOT NULL DEFAULT 0,           -- its position in the statement as printed
    page           INTEGER NOT NULL,                     -- PDF page number
    amount         REAL,                                 -- the amount printed on that line
    coefficient    REAL NOT NULL DEFAULT 1,              -- +1 or -1 when lines are combined
    section        TEXT NOT NULL DEFAULT ''              -- the heading the line is printed under
);
CREATE INDEX IF NOT EXISTS ix_figure_lines_figure ON figure_lines(figure_id);

-- Before and after for every change. Restore reads it.
CREATE TABLE IF NOT EXISTS figure_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    figure_id    INTEGER NOT NULL REFERENCES figures(id) ON DELETE CASCADE,
    action       TEXT NOT NULL,                          -- save, edit, clear, move, confirm, restore, calculate
    actor_kind   TEXT NOT NULL CHECK (actor_kind IN ('agent', 'person', 'calculated', 'import')),
    actor_name   TEXT NOT NULL DEFAULT '',
    changed_at   TEXT NOT NULL,
    before_json  TEXT,                                   -- NULL when the figure was new
    after_json   TEXT NOT NULL,
    round_id     INTEGER,                                -- the correction round that made the write, if any
    comment_ids_json TEXT                                -- the round's comments the write served, e.g. [4, 5]
);
CREATE INDEX IF NOT EXISTS ix_figure_history_figure ON figure_history(figure_id, id);
CREATE INDEX IF NOT EXISTS ix_figure_history_round ON figure_history(round_id);

-- Notes (step 6) ---------------------------------------------------------
-- A note's words are copied from the Reader's page content by code; the
-- look sits beside them in blocks_json (app/notes/blocks.py). Every write
-- goes through app/notes/store.py and adds a note_history row.

CREATE TABLE IF NOT EXISTS notes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    note_number      TEXT NOT NULL DEFAULT '',           -- as printed, or '' when it cannot be read
    title            TEXT NOT NULL DEFAULT '',           -- as printed
    pages_json       TEXT NOT NULL DEFAULT '[]',         -- the PDF pages its blocks come from
    template_id      TEXT,                               -- the field's template; NULL when not placed
    node_uuid        TEXT,                               -- notes_nodes.node_uuid; NULL when not placed. Not a
                                                         -- foreign key, so the catalogue can be rebuilt
    part             INTEGER NOT NULL DEFAULT 1,         -- part n of `parts`, for a first-level split
    parts            INTEGER NOT NULL DEFAULT 1,
    position         INTEGER NOT NULL DEFAULT 0,         -- order among the notes of one field
    blocks_json      TEXT NOT NULL,                      -- NoteBody
    format_state     TEXT NOT NULL DEFAULT 'fine' CHECK (format_state IN ('fine', 'check_formatting', 'not_sure')),
    format_reason    TEXT NOT NULL DEFAULT '',
    certainty        TEXT NOT NULL DEFAULT 'sure' CHECK (certainty IN ('sure', 'unsure')),
    certainty_reason TEXT NOT NULL DEFAULT '',
    confirmed_by     TEXT,
    confirmed_at     TEXT,
    revision         INTEGER NOT NULL DEFAULT 1,
    updated_by       TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_notes_run ON notes(run_id, node_uuid, position);

-- Before and after for every note change. Undo reads it.
CREATE TABLE IF NOT EXISTS note_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id          INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    run_id           INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    action           TEXT NOT NULL CHECK (action IN ('place', 'look', 'move', 'clear', 'confirm', 'redo', 'restore')),
    actor_kind       TEXT NOT NULL CHECK (actor_kind IN ('agent', 'person')),
    actor_name       TEXT NOT NULL DEFAULT '',           -- the agent's name or the person's email
    before_json      TEXT,                               -- NULL when the note was new
    after_json       TEXT NOT NULL,
    round_id         INTEGER,                            -- the correction round that made the write, if any
    comment_ids_json TEXT,                               -- the round's comments the write served, e.g. [4, 5]
    reason           TEXT NOT NULL DEFAULT '',
    changed_at       TEXT NOT NULL,
    settled_reports_json TEXT                            -- a person's confirm: the gap reports it settled, e.g. [3]
);
CREATE INDEX IF NOT EXISTS ix_note_history_note ON note_history(note_id, id);
CREATE INDEX IF NOT EXISTS ix_note_history_round ON note_history(round_id);

-- The notes agent's coverage record: what it could not place, and why.
CREATE TABLE IF NOT EXISTS note_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('source_gap', 'missing_mandatory_field', 'routed_elsewhere')),
    note_number TEXT NOT NULL DEFAULT '',
    node_uuid   TEXT,                                    -- the field concerned, if any
    pages_json  TEXT NOT NULL DEFAULT '[]',
    reason      TEXT NOT NULL,
    actor_name  TEXT NOT NULL DEFAULT '',
    after_block TEXT,                                    -- a source gap falls after this block of its note
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'settled')),
    settled_by  TEXT,                                    -- the person who confirmed the note or left the field empty
    settled_at  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_note_reports_run ON note_reports(run_id);

-- Checks ---------------------------------------------------------------
-- Rewritten for the whole run each time a figure in the run changes.

CREATE TABLE IF NOT EXISTS check_results (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    check_name           TEXT NOT NULL,
    entity_scope         TEXT NOT NULL,                  -- Group and Company are checked separately
    status               TEXT NOT NULL CHECK (status IN (
                             'passed', 'failed', 'warning', 'not_assessed', 'not_applicable')),
    period               TEXT,                           -- the period the numbers below are from
    expected             REAL,
    actual               REAL,
    diff                 REAL,
    tolerance            REAL,
    message              TEXT NOT NULL,
    comparands_json      TEXT,
    target_concept_uuid  TEXT,                           -- where the review list jumps to
    computed_at          TEXT NOT NULL,
    UNIQUE (run_id, check_name, entity_scope)
);

-- Scoring (step 2) -----------------------------------------------------
-- One workbook a person filled per run. The file sits in the run's folder;
-- its cells are read once, when it is attached. The comparison with the
-- run's figures is worked out on every read (app/scoring/attached.py).

CREATE TABLE IF NOT EXISTS filled_workbooks (
    run_id       INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,                          -- as uploaded
    sha256       TEXT NOT NULL,
    stored_path  TEXT NOT NULL,                          -- relative to the output folder
    layout       TEXT NOT NULL CHECK (layout IN ('mtool', 'template')),
    uploaded_by  TEXT NOT NULL,
    uploaded_at  TEXT NOT NULL,
    loose_json   TEXT NOT NULL DEFAULT '[]',             -- numbers no field claims
    read_for     TEXT NOT NULL DEFAULT '[]'              -- the run's template ids when read; re-read when they change
);

-- One row per field cell the workbook holds, blank ones included, keyed as figures are.
CREATE TABLE IF NOT EXISTS filled_workbook_cells (
    run_id           INTEGER NOT NULL REFERENCES filled_workbooks(run_id) ON DELETE CASCADE,
    concept_uuid     TEXT NOT NULL,
    period           TEXT NOT NULL,
    entity_scope     TEXT NOT NULL,
    dimension_key    TEXT NOT NULL DEFAULT '',
    value            REAL,                               -- blank, or a total left to its formula
    is_formula       INTEGER NOT NULL DEFAULT 0,         -- a formula sits in a total's cell
    workbook_cell    TEXT,                               -- Sheet!B12
    unread_reason    TEXT,                               -- set when the cell could not be read or trusted
    unread_sentence  TEXT,
    holds_value      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, concept_uuid, period, entity_scope, dimension_key)
);

-- One row per note field the workbook holds text in. Only the text's short lines are kept, to find a
-- note's printed number and title; wording is not compared (app/scoring/workbook_notes.py).
CREATE TABLE IF NOT EXISTS filled_workbook_notes (
    run_id           INTEGER NOT NULL REFERENCES filled_workbooks(run_id) ON DELETE CASCADE,
    field_id         TEXT NOT NULL,                      -- the note field, as notes.node_uuid
    workbook_cell    TEXT,                               -- Sheet!E12
    lines_json       TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, field_id)
);

-- Starting workbook (step 10d) -----------------------------------------
-- A part-filled mTool workbook a person attached at setup (app/starting/).
-- The file sits in the run's folder. Its figures are imported when the setup
-- is confirmed: figures with origin prior_workbook or typed_in_workbook whose
-- source_ref holds this workbook's sha256 and the cell they came from.

CREATE TABLE IF NOT EXISTS starting_workbooks (
    run_id       INTEGER PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    filename     TEXT NOT NULL,                          -- as uploaded
    sha256       TEXT NOT NULL,
    stored_path  TEXT NOT NULL,                          -- relative to the output folder
    facts_json   TEXT NOT NULL DEFAULT '{}',             -- what it says of itself: standard, level, unit, year end
    uploaded_by  TEXT NOT NULL,
    uploaded_at  TEXT NOT NULL,
    imported_at  TEXT,                                   -- set once its figures are imported, at confirm
    import_json  TEXT                                    -- the import's counts and the cells it did not import
);

-- The report's comparative as an agent read it, for a last-year figure imported from the starting
-- workbook (step 10e). The imported figure itself never changes.
CREATE TABLE IF NOT EXISTS prior_year_comparisons (
    figure_id       INTEGER PRIMARY KEY REFERENCES figures(id) ON DELETE CASCADE,
    run_id          INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    report_value    REAL NOT NULL,                       -- the latest reading, in the sign the field stores
    disputed_value  REAL,                                -- the first sign-only reading, kept while that is open
    page            INTEGER,
    printed_label   TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL DEFAULT '',
    compared_by     TEXT NOT NULL,
    compared_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_prior_year_comparisons_run ON prior_year_comparisons(run_id);


-- Review (step 5a) -----------------------------------------------------
-- Comments, correction rounds and which comments each round carried
-- (app/review/). What a round changed is read from figure_history.round_id.

CREATE TABLE IF NOT EXISTS comments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    author_kind       TEXT NOT NULL CHECK (author_kind IN ('person', 'agent')),
    author_name       TEXT NOT NULL,                     -- the person's email or the agent's name
    target_kind       TEXT NOT NULL CHECK (target_kind IN ('figure', 'line', 'statement', 'note')),
    statement         TEXT,                              -- SOFP, SOPL, ...
    concept_uuid      TEXT,                              -- figure and line targets
    period            TEXT,                              -- figure targets: CY or PY
    entity_scope      TEXT,                              -- figure and line targets
    dimension_key     TEXT NOT NULL DEFAULT '',
    note_id           INTEGER,                           -- note targets: notes.id
    note_part_json    TEXT,                              -- note targets: {block, scope, row, column}; NULL = whole
    text              TEXT NOT NULL,
    scope             TEXT NOT NULL DEFAULT 'figure' CHECK (scope IN ('figure', 'run', 'company')),
    status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN (
                          'open', 'sent', 'answered', 'accepted', 'undone', 'done')),
    outcome           TEXT CHECK (outcome IN ('changed', 'not_changed', 'question')),
    answer            TEXT,                              -- the agent's one sentence
    proposed_guidance TEXT,                              -- a proposed company guidance line
    guidance_status   TEXT CHECK (guidance_status IN ('added', 'dismissed')),   -- what a person did with it
    guidance_version  INTEGER,                           -- the company guidance version that added it
    round_id          INTEGER,                           -- the round that last carried it (or left it)
    thread_json       TEXT NOT NULL DEFAULT '[]',        -- earlier answers and the replies, oldest first
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    closed_by         TEXT,                              -- who accepted, undid or marked it done
    report_id         INTEGER                            -- a comment on the notes about one report (note_reports.id)
);
CREATE INDEX IF NOT EXISTS ix_comments_run ON comments(run_id, status);

CREATE TABLE IF NOT EXISTS rounds (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id             INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    number             INTEGER NOT NULL,                 -- 1, 2, ... within the run
    status             TEXT NOT NULL DEFAULT 'sent' CHECK (status IN (
                           'sent', 'working', 'done', 'failed', 'stopped')),
    sent_by            TEXT NOT NULL,
    client_id          TEXT,                             -- the browser's id for one press of Send
    job_id             INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    stop_requested     INTEGER NOT NULL DEFAULT 0,
    checks_before_json TEXT NOT NULL DEFAULT '[]',       -- the check results when the round was sent
    summary            TEXT,                             -- the Reviewer's one sentence
    error              TEXT,                             -- the plain sentence of a round that did not finish
    sent_at            TEXT NOT NULL,
    started_at         TEXT,
    finished_at        TEXT,
    UNIQUE (run_id, number),
    UNIQUE (run_id, client_id)
);
-- At most one round per run waits or works: a second Send is refused by the database too.
CREATE UNIQUE INDEX IF NOT EXISTS ux_rounds_active ON rounds(run_id) WHERE status IN ('sent', 'working');

CREATE TABLE IF NOT EXISTS round_comments (
    round_id     INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    comment_id   INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    outcome      TEXT,                                   -- this round's answer, kept when the comment is sent again
    answer       TEXT,
    answered_at  TEXT,
    PRIMARY KEY (round_id, comment_id)
);

-- Scope questions and guidance (step 5b) ---------------------------------

-- A question the figures agent asked about the run's scope (app/scope/).
CREATE TABLE IF NOT EXISTS scope_questions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage          TEXT NOT NULL,                        -- the stage that asked: extract
    asked_by       TEXT NOT NULL,                        -- the agent's name
    field          TEXT NOT NULL CHECK (field IN ('standard', 'level', 'year_end', 'unit', 'layout')),
    statement      TEXT,                                 -- for a layout question
    question       TEXT NOT NULL,
    evidence_json  TEXT NOT NULL,                        -- [{"text", "page"}]
    choices_json   TEXT NOT NULL,                        -- [{"label", "value", "effect", "suggested"}]
    setup_value    TEXT NOT NULL,                        -- the confirmed value when it was asked
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'answered')),
    asked_at       TEXT NOT NULL,
    job_id         INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    answer_choice  INTEGER,                              -- the index of the choice taken, or NULL
    answer_text    TEXT,                                 -- the person's own words, or NULL
    answer_value   TEXT,                                 -- the setup value the answer chose, or NULL
    setup_changed  INTEGER NOT NULL DEFAULT 0,
    cleared        INTEGER NOT NULL DEFAULT 0,           -- agent figures cleared by the setup change
    answered_by    TEXT,
    answered_at    TEXT
);
-- One open question per run at a time.
CREATE UNIQUE INDEX IF NOT EXISTS ux_scope_questions_open ON scope_questions(run_id) WHERE status = 'open';

-- Firm guidance (company_id NULL) and company guidance, each saved as whole versions.
CREATE TABLE IF NOT EXISTS guidance_versions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id    INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    version       INTEGER NOT NULL,                      -- 1, 2, ... per company, or for the firm
    lines_json    TEXT NOT NULL,                         -- the full list of lines
    saved_by      TEXT NOT NULL,
    saved_at      TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('typed', 'proposed', 'restored')),
    comment_id    INTEGER,                               -- the comment whose proposed line was added
    restored_from INTEGER                                -- the version a restore copied
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_guidance_versions ON guidance_versions(COALESCE(company_id, 0), version);

-- The guidance versions a run's agent was given, each time extraction or a round started.
CREATE TABLE IF NOT EXISTS run_guidance (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    stage            TEXT NOT NULL,                      -- extract or round
    round_id         INTEGER,
    company_id       INTEGER,
    firm_version     INTEGER NOT NULL,                   -- 0 when there was none
    company_version  INTEGER NOT NULL,
    used_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_run_guidance_run ON run_guidance(run_id);

-- mTool fill (step 8e) --------------------------------------------------
-- One row per fill: the template a person uploaded, the job that fills a
-- copy of it, and the receipt (app/filing/receipts.py). Both files sit in the
-- run's folder; the upload is never changed. A trimmed v1 receipt.

CREATE TABLE IF NOT EXISTS fills (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id               INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    job_id               INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
    created_by           TEXT NOT NULL,
    created_at           TEXT NOT NULL,
    job_status           TEXT NOT NULL DEFAULT 'queued' CHECK (job_status IN (
                             'queued', 'filling', 'ready', 'failed')),
    error                TEXT,                           -- the plain sentence of a fill that failed
    template_filename    TEXT NOT NULL,                  -- as uploaded
    template_path        TEXT NOT NULL,                  -- relative to the output folder
    template_sha256      TEXT NOT NULL,
    template_fingerprint TEXT,
    compatibility        TEXT,                           -- known, probably_compatible or unknown
    figures_digest       TEXT,                           -- which revision of the figures was filled
    notes_digest         TEXT,
    output_path          TEXT,                           -- relative to the output folder
    output_sha256        TEXT,
    status               TEXT CHECK (status IN ('ok', 'needs review')),
    report_json          TEXT,                           -- written, kept, skipped, unresolved, mismatched, notes
    started_at           TEXT,
    finished_at          TEXT,
    downloaded_at        TEXT,
    -- Step 12: the investigating agent looks for places for the figures the fill could not place.
    investigation        TEXT CHECK (investigation IN ('queued', 'working', 'done', 'failed')),
    investigation_error  TEXT                            -- its one plain sentence when it failed
);
CREATE INDEX IF NOT EXISTS ix_fills_run ON fills(run_id, id);
-- At most one fill per run waits or works.
CREATE UNIQUE INDEX IF NOT EXISTS ux_fills_active ON fills(run_id) WHERE job_status IN ('queued', 'filling');

-- Template investigation (step 12) --------------------------------------
-- A cell the investigating agent proposes for a figure the fill could not place, with its evidence. The
-- agent writes only here; a person chooses Use or Skip. It never writes a workbook or a mapping.
CREATE TABLE IF NOT EXISTS placements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_id       INTEGER NOT NULL REFERENCES fills(id) ON DELETE CASCADE,
    concept_uuid  TEXT NOT NULL,
    period        TEXT NOT NULL,
    entity_scope  TEXT NOT NULL,
    dimension_key TEXT NOT NULL DEFAULT '',
    figure_name   TEXT NOT NULL,                  -- the figure in words, as the receipt names it
    sheet         TEXT NOT NULL,
    cell          TEXT NOT NULL,                  -- such as E30
    place         TEXT NOT NULL,                  -- the cell in words: sheet, row label, column heading
    evidence      TEXT NOT NULL,                  -- why this cell, in one or two plain sentences
    -- not_found: the agent looked and found no single cell; `evidence` holds why, sheet and cell are empty.
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'used', 'skipped', 'not_found')),
    created_at    TEXT NOT NULL,
    decided_by    TEXT,
    decided_at    TEXT,
    UNIQUE (fill_id, concept_uuid, period, entity_scope, dimension_key)
);
CREATE INDEX IF NOT EXISTS ix_placements_fill ON placements(fill_id, id);

-- Placements a person confirmed for a template, by its fingerprint: they make the template known and the
-- fill uses them for the figures it cannot place itself (app/filing/plan.py, `confirmed`).
CREATE TABLE IF NOT EXISTS template_mappings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint   TEXT NOT NULL UNIQUE,
    name          TEXT,                           -- the template's file name when first confirmed
    cells_json    TEXT NOT NULL,                  -- [{concept_uuid, period, entity_scope, dimension_key, sheet, row, col}]
    confirmed_by  TEXT NOT NULL,
    confirmed_at  TEXT NOT NULL
);

-- Reports (step 10) -----------------------------------------------------
-- The directors' report, the statement by directors and the auditors' report:
-- one row per field a person or the reports agent has assessed. A field with
-- no row is not assessed yet. The narrative's words are copied from the
-- Reader's page content by code, as a note's are (blocks_json, a NoteBody);
-- the other fields hold their value as text. Every write goes through
-- app/reports/store.py and adds a report_field_history row.

CREATE TABLE IF NOT EXISTS report_fields (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    report       TEXT NOT NULL CHECK (report IN ('DIRECTORS_REPORT', 'STATEMENT_BY_DIRECTORS', 'AUDITORS_REPORT')),
    element_id   TEXT NOT NULL,                          -- the taxonomy element, e.g. ssmt_NameOfAuditFirm
    kind         TEXT NOT NULL CHECK (kind IN ('html', 'date', 'choice', 'text')),
    status       TEXT NOT NULL CHECK (status IN ('filled', 'not_shown', 'unsure', 'cleared')),
    value        TEXT,                                   -- NULL unless filled; never NULL written as text
    blocks_json  TEXT,                                   -- the narrative's NoteBody; NULL for other fields
    reason       TEXT NOT NULL DEFAULT '',               -- why it is left empty, or what on the page shows it
    pages_json   TEXT NOT NULL DEFAULT '[]',             -- the PDF pages it was read from
    revision     INTEGER NOT NULL DEFAULT 1,
    actor_kind   TEXT NOT NULL CHECK (actor_kind IN ('agent', 'person')),
    updated_by   TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    UNIQUE(run_id, report, element_id)
);

CREATE TABLE IF NOT EXISTS report_field_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    field_id     INTEGER NOT NULL REFERENCES report_fields(id) ON DELETE CASCADE,
    action       TEXT NOT NULL CHECK (action IN ('save', 'edit', 'clear')),
    actor_kind   TEXT NOT NULL CHECK (actor_kind IN ('agent', 'person')),
    actor_name   TEXT NOT NULL DEFAULT '',
    before_json  TEXT,                                   -- NULL when the field was not assessed before
    after_json   TEXT NOT NULL,
    changed_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_report_field_history_field ON report_field_history(field_id, id);

-- Issues people report (go-live A2) -----------------------------------------
-- A report keeps the run that was on screen. The run's name is copied, so the
-- list still reads well once the run itself is deleted.

CREATE TABLE IF NOT EXISTS issues (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_email TEXT NOT NULL,                        -- text, not a key: outlives the account
    text           TEXT NOT NULL,
    run_id         INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    run_label      TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    note           TEXT NOT NULL DEFAULT '',             -- the admin's note
    file_name      TEXT,                                 -- the screenshot as uploaded, for display
    file_path      TEXT,                                 -- relative to the output folder
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
