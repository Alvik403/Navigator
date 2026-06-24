-- HR: written remarks (замечания) to staff — curators, instructors, etc.

CREATE TABLE IF NOT EXISTS app.staff_remarks (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    text        TEXT        NOT NULL,
    issued_by   UUID        REFERENCES app.users (id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_staff_remarks_user_id ON app.staff_remarks (user_id);
CREATE INDEX IF NOT EXISTS idx_staff_remarks_created_at ON app.staff_remarks (created_at DESC);
