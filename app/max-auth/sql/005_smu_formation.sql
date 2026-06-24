-- SMU shift patterns, formation weights, instructor binding.

CREATE TABLE IF NOT EXISTS app.smu_patterns (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    code         VARCHAR(80)  NOT NULL UNIQUE,
    name         VARCHAR(255) NOT NULL,
    work_days    INT          NOT NULL DEFAULT 2 CHECK (work_days >= 1),
    off_days     INT          NOT NULL DEFAULT 0 CHECK (off_days >= 0),
    anchor_date  DATE         NOT NULL DEFAULT CURRENT_DATE,
    status       VARCHAR(50)  NOT NULL DEFAULT 'active',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_smu_patterns_status ON app.smu_patterns (status);

CREATE TABLE IF NOT EXISTS app.user_smu (
    user_id         UUID        NOT NULL PRIMARY KEY REFERENCES app.users (id) ON DELETE CASCADE,
    smu_pattern_id  UUID        NOT NULL REFERENCES app.smu_patterns (id) ON DELETE RESTRICT,
    started_at      DATE        NOT NULL DEFAULT CURRENT_DATE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_smu_pattern_id ON app.user_smu (smu_pattern_id);

CREATE TABLE IF NOT EXISTS app.smu_extra_shifts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    shift_date  DATE        NOT NULL,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (user_id, shift_date)
);

CREATE INDEX IF NOT EXISTS idx_smu_extra_shifts_date ON app.smu_extra_shifts (shift_date);

CREATE TABLE IF NOT EXISTS app.track_formation_weights (
    user_id           UUID           NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    track_id          UUID           NOT NULL REFERENCES app.tracks (id) ON DELETE CASCADE,
    weight            NUMERIC(12, 4) NOT NULL DEFAULT 0,
    assigned_count    INT            NOT NULL DEFAULT 0 CHECK (assigned_count >= 0),
    last_assigned_at  TIMESTAMPTZ,
    lock_until        DATE,
    updated_at        TIMESTAMPTZ      NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, track_id)
);

CREATE INDEX IF NOT EXISTS idx_track_formation_weights_track ON app.track_formation_weights (track_id);
CREATE INDEX IF NOT EXISTS idx_track_formation_weights_lock ON app.track_formation_weights (lock_until);

ALTER TABLE app.groups
    ADD COLUMN IF NOT EXISTS instructor_id UUID REFERENCES app.users (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_groups_instructor_id ON app.groups (instructor_id);

INSERT INTO app.smu_patterns (code, name, work_days, off_days, anchor_date)
VALUES
    ('smu-1', 'СМУ-1', 2, 2, DATE '2026-01-01'),
    ('smu-2', 'СМУ-2', 2, 2, DATE '2026-01-02')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    work_days = EXCLUDED.work_days,
    off_days = EXCLUDED.off_days,
    updated_at = now();
