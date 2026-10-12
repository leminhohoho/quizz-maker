CREATE TABLE quiz (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    course TEXT NOT NULL,
    current_revision INTEGER NOT NULL
);

CREATE TABLE quiz_revision (
    quiz_id TEXT NOT NULL REFERENCES quiz(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    package_json TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (quiz_id, revision)
);

CREATE TABLE question (
    quiz_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    question_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    type TEXT NOT NULL,
    points INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    PRIMARY KEY (quiz_id, revision, question_id),
    FOREIGN KEY (quiz_id, revision) REFERENCES quiz_revision(quiz_id, revision) ON DELETE CASCADE
);

CREATE TABLE asset (
    quiz_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    path TEXT NOT NULL,
    mime TEXT NOT NULL,
    bytes BLOB NOT NULL,
    PRIMARY KEY (quiz_id, revision, path),
    FOREIGN KEY (quiz_id, revision) REFERENCES quiz_revision(quiz_id, revision) ON DELETE CASCADE
);

CREATE TABLE attempt (
    id INTEGER PRIMARY KEY,
    quiz_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    score REAL,
    max_score REAL NOT NULL,
    FOREIGN KEY (quiz_id, revision) REFERENCES quiz_revision(quiz_id, revision) ON DELETE CASCADE
);

CREATE TABLE answer (
    attempt_id INTEGER NOT NULL REFERENCES attempt(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    response_json TEXT NOT NULL,
    verdict_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('graded', 'pending_agent')),
    score REAL NOT NULL,
    graded_at TEXT NOT NULL,
    PRIMARY KEY (attempt_id, question_id)
);

CREATE TABLE setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
