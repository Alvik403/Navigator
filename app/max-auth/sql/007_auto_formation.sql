-- Auto formation: program deadlines and optional group-less lessons.

ALTER TABLE app.tracks
    ADD COLUMN IF NOT EXISTS completion_days INT NOT NULL DEFAULT 90 CHECK (completion_days >= 1);

ALTER TABLE app.user_tracks
    ADD COLUMN IF NOT EXISTS due_date DATE;

UPDATE app.user_tracks ut
SET due_date = ut.started_at + (t.completion_days || ' days')::interval
FROM app.tracks t
WHERE t.id = ut.track_id
  AND ut.due_date IS NULL
  AND ut.status = 'active';

ALTER TABLE app.lessons
    ALTER COLUMN group_id DROP NOT NULL;

CREATE TABLE IF NOT EXISTS app.formation_auto_log (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    track_id    UUID        NOT NULL REFERENCES app.tracks (id) ON DELETE CASCADE,
    slot_id     UUID        REFERENCES app.conveyor_slots (id) ON DELETE SET NULL,
    lesson_id   UUID        REFERENCES app.lessons (id) ON DELETE SET NULL,
    lesson_date DATE        NOT NULL,
    status      VARCHAR(30) NOT NULL,
    detail      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_formation_auto_log_date ON app.formation_auto_log (lesson_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_formation_auto_log_unique
    ON app.formation_auto_log (track_id, slot_id, lesson_date)
    WHERE status = 'created' AND slot_id IS NOT NULL;
