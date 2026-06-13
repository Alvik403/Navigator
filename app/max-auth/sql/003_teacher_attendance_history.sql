CREATE TABLE IF NOT EXISTS app.attendance_mark_history (
    id          UUID                  PRIMARY KEY DEFAULT gen_random_uuid(),
    mark_id     UUID                  NOT NULL REFERENCES app.attendance_marks (id) ON DELETE CASCADE,
    user_id     UUID                  NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    lesson_id   UUID                  NOT NULL REFERENCES app.lessons (id) ON DELETE CASCADE,
    old_status  app.attendance_status,
    new_status  app.attendance_status NOT NULL,
    changed_by  UUID                  NOT NULL REFERENCES app.users (id) ON DELETE RESTRICT,
    changed_at  TIMESTAMPTZ           NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_attendance_mark_history_lesson_id
    ON app.attendance_mark_history (lesson_id);

CREATE INDEX IF NOT EXISTS idx_attendance_mark_history_changed_at
    ON app.attendance_mark_history (changed_at DESC);
