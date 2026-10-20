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
