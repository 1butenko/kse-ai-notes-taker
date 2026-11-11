-- Applied by `uv run python -m app.manage init-db` (`make db-init`). Safe to run more than once.
-- The AI Note Taker's data. The app's courses themselves live in the uploads directory; a row
-- here links one of them (`course_key`, its Moodle course id) to its fetched materials and runs.

CREATE TABLE IF NOT EXISTS courses (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title      text NOT NULL CHECK (length(btrim(title)) > 0),
    -- The course's index in the S3 bucket. Derived from id, so it can never drift.
    s3_prefix  text GENERATED ALWAYS AS ('courses/' || id::text || '/') STORED UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS courses_created_at_idx ON courses (created_at DESC);

-- The Moodle course a course is synced from.
ALTER TABLE courses ADD COLUMN IF NOT EXISTS moodle_course_id bigint;

-- The app's course key (the uploads folder name) this row belongs to.
ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_key text UNIQUE;

-- Course files fetched from Moodle by the AI Note Taker's `moodle` subagent.
CREATE TABLE IF NOT EXISTS materials (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id           uuid NOT NULL REFERENCES courses (id) ON DELETE CASCADE,
    moodle_module_id    bigint NOT NULL,
    section             int NOT NULL DEFAULT 0,
    section_name        text NOT NULL DEFAULT '',
    name                text NOT NULL,
    mimetype            text NOT NULL DEFAULT '',
    size                bigint NOT NULL DEFAULT 0,
    s3_key              text NOT NULL UNIQUE,
    source_url          text NOT NULL,
    moodle_timemodified bigint NOT NULL DEFAULT 0,
    reason              text NOT NULL DEFAULT '',
    fetched_at          timestamptz NOT NULL DEFAULT now(),
    -- A re-run skips a file that is unchanged in Moodle.
    UNIQUE (course_id, source_url, moodle_timemodified)
);

ALTER TABLE materials ADD COLUMN IF NOT EXISTS section int NOT NULL DEFAULT 0;
ALTER TABLE materials ADD COLUMN IF NOT EXISTS section_name text NOT NULL DEFAULT '';

-- The course's topics: its Moodle sections, saved when the `moodle` subagent lists the course.
CREATE TABLE IF NOT EXISTS course_topics (
    course_id uuid NOT NULL REFERENCES courses (id) ON DELETE CASCADE,
    section   int NOT NULL,
    name      text NOT NULL DEFAULT '',
    summary   text NOT NULL DEFAULT '',
    PRIMARY KEY (course_id, section)
);

-- One row per AI Note Taker run for a course.
CREATE TABLE IF NOT EXISTS sync_runs (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id   uuid NOT NULL REFERENCES courses (id) ON DELETE CASCADE,
    focus       text,
    status      text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    report      text,
    error       text,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

-- What the agent is doing right now, shown while the run is going.
ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS step text;
-- The agent's todo list [{content, status}] and its latest actions [{text, status, detail}].
ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS todos jsonb NOT NULL DEFAULT '[]';
ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS actions jsonb NOT NULL DEFAULT '[]';

CREATE INDEX IF NOT EXISTS sync_runs_course_idx ON sync_runs (course_id, started_at DESC);

-- One row per run of the lecture-notes agent (app/note_taker/lecture_notes) for one lecture.
CREATE TABLE IF NOT EXISTS lecture_note_runs (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id            uuid NOT NULL REFERENCES courses (id) ON DELETE CASCADE,
    -- The lecture: its session id in the course plan, and its label when the run started.
    session_id           text NOT NULL,
    session_label        text NOT NULL DEFAULT '',
    status               text NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'failed', 'cancelled')),
    step                 text,
    todos                jsonb NOT NULL DEFAULT '[]',
    actions              jsonb NOT NULL DEFAULT '[]',
    report               text,
    error                text,
    -- The published page: courses/<course-id>/lecture-notes/<session>/<run>/ and its files.
    s3_prefix            text,
    files                jsonb NOT NULL DEFAULT '[]',
    -- The lecture's readings when the run started (app.plan.session_fingerprint).
    readings_fingerprint text NOT NULL DEFAULT '',
    model                text,
    -- Langfuse prompt and skill versions the run used ({"prompts": {...}, "skills": {...}}).
    prompt_versions      jsonb NOT NULL DEFAULT '{}',
    langfuse_trace_id    text,
    renders              int NOT NULL DEFAULT 0,
    started_at           timestamptz NOT NULL DEFAULT now(),
    finished_at          timestamptz
);

CREATE INDEX IF NOT EXISTS lecture_note_runs_session_idx
    ON lecture_note_runs (course_id, session_id, started_at DESC);
