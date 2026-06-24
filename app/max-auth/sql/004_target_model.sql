-- Target model: tracks, conveyor slots, HR-owned attendance, curator scope.

CREATE TABLE IF NOT EXISTS app.tracks (
    id                  UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    code                VARCHAR(80)  NOT NULL UNIQUE,
    name                VARCHAR(255) NOT NULL,
    description         TEXT,
    practice_required   INT          NOT NULL DEFAULT 0 CHECK (practice_required >= 0),
    lecture_required    INT          NOT NULL DEFAULT 0 CHECK (lecture_required >= 0),
    id_hr               UUID         REFERENCES app.users (id) ON DELETE SET NULL,
    status              VARCHAR(50)  NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tracks_id_hr ON app.tracks (id_hr);
CREATE INDEX IF NOT EXISTS idx_tracks_status ON app.tracks (status);

CREATE TABLE IF NOT EXISTS app.user_tracks (
    user_id      UUID        NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    track_id     UUID        NOT NULL REFERENCES app.tracks (id) ON DELETE CASCADE,
    status       VARCHAR(50) NOT NULL DEFAULT 'active',
    started_at   DATE        NOT NULL DEFAULT CURRENT_DATE,
    completed_at DATE,
    assigned_by  UUID        REFERENCES app.users (id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, track_id),
    CHECK (completed_at IS NULL OR completed_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_user_tracks_track_id ON app.user_tracks (track_id);
CREATE INDEX IF NOT EXISTS idx_user_tracks_status ON app.user_tracks (status);
CREATE INDEX IF NOT EXISTS idx_user_tracks_assigned_by ON app.user_tracks (assigned_by);

CREATE TABLE IF NOT EXISTS app.conveyor_slots (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    code            VARCHAR(80)  NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    starts_at_local TIME         NOT NULL,
    duration_min    INT          NOT NULL DEFAULT 60 CHECK (duration_min > 0),
    timezone        VARCHAR(80)  NOT NULL DEFAULT 'Europe/Moscow',
    status          VARCHAR(50)  NOT NULL DEFAULT 'active',
    sort_order      INT          NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conveyor_slots_status ON app.conveyor_slots (status);
CREATE INDEX IF NOT EXISTS idx_conveyor_slots_sort_order ON app.conveyor_slots (sort_order);

CREATE TABLE IF NOT EXISTS app.track_teachers (
    track_id   UUID        NOT NULL REFERENCES app.tracks (id) ON DELETE CASCADE,
    teacher_id UUID        NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (track_id, teacher_id)
);

CREATE INDEX IF NOT EXISTS idx_track_teachers_teacher_id ON app.track_teachers (teacher_id);

ALTER TABLE app.lessons
    ADD COLUMN IF NOT EXISTS track_id UUID REFERENCES app.tracks (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS slot_id UUID REFERENCES app.conveyor_slots (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS reporting_group_id UUID REFERENCES app.groups (id) ON DELETE SET NULL;

UPDATE app.lessons
SET reporting_group_id = group_id
WHERE reporting_group_id IS NULL
  AND group_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_lessons_track_id ON app.lessons (track_id);
CREATE INDEX IF NOT EXISTS idx_lessons_slot_id ON app.lessons (slot_id);
CREATE INDEX IF NOT EXISTS idx_lessons_reporting_group_id ON app.lessons (reporting_group_id);

ALTER TABLE app.lesson_members
    ADD COLUMN IF NOT EXISTS role_in_lesson VARCHAR(50) NOT NULL DEFAULT 'employee',
    ADD COLUMN IF NOT EXISTS track_id UUID REFERENCES app.tracks (id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_lesson_members_role_in_lesson ON app.lesson_members (role_in_lesson);
CREATE INDEX IF NOT EXISTS idx_lesson_members_track_id ON app.lesson_members (track_id);

ALTER TABLE app.attendance_marks
    ADD COLUMN IF NOT EXISTS subject_role VARCHAR(50) NOT NULL DEFAULT 'employee',
    ADD COLUMN IF NOT EXISTS marked_by_role VARCHAR(50);

CREATE INDEX IF NOT EXISTS idx_attendance_marks_subject_role ON app.attendance_marks (subject_role);

ALTER TABLE app.strikes
    ADD COLUMN IF NOT EXISTS target_role VARCHAR(50);

UPDATE app.strikes s
SET target_role = r.code
FROM app.profiles p
JOIN app.roles r ON r.id = p.role_id
WHERE p.user_id = s.user_id
  AND s.target_role IS NULL;

CREATE INDEX IF NOT EXISTS idx_strikes_target_role ON app.strikes (target_role);

INSERT INTO app.conveyor_slots (code, name, starts_at_local, duration_min, sort_order)
VALUES
    ('slot-09-00', '09:00', '09:00', 60, 10),
    ('slot-10-30', '10:30', '10:30', 60, 20),
    ('slot-12-00', '12:00', '12:00', 60, 30),
    ('slot-14-00', '14:00', '14:00', 60, 40),
    ('slot-15-30', '15:30', '15:30', 60, 50)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    starts_at_local = EXCLUDED.starts_at_local,
    duration_min = EXCLUDED.duration_min,
    sort_order = EXCLUDED.sort_order,
    updated_at = now();
