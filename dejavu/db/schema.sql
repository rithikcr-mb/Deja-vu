CREATE TABLE IF NOT EXISTS player_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    display_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_sessions (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('in_progress', 'completed', 'defeated', 'abandoned')
    ),
    origin TEXT NOT NULL CHECK (origin IN ('player', 'seeded_demo'))
);

CREATE TABLE IF NOT EXISTS weak_concepts (
    id INTEGER PRIMARY KEY,
    normalized_label TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    explanation TEXT NOT NULL,
    first_missed_at TEXT NOT NULL,
    last_missed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mistake_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES learning_sessions(id),
    question_instance_id TEXT NOT NULL,
    weak_concept_id INTEGER NOT NULL REFERENCES weak_concepts(id),
    origin TEXT NOT NULL CHECK (origin IN ('player', 'seeded_demo')),
    question_kind TEXT NOT NULL CHECK (question_kind IN ('regular', 'boss')),
    question_text TEXT NOT NULL,
    chosen_answer TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    explanation TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    UNIQUE (session_id, question_instance_id)
);

CREATE INDEX IF NOT EXISTS idx_mistake_events_concept_time
    ON mistake_events (weak_concept_id, occurred_at DESC);

PRAGMA user_version = 2;
