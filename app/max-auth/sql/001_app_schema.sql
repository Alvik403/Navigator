CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS app;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typnamespace = 'app'::regnamespace AND typname = 'attendance_status') THEN
        CREATE TYPE app.attendance_status AS ENUM ('present', 'absent', 'late');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typnamespace = 'app'::regnamespace AND typname = 'strike_status') THEN
        CREATE TYPE app.strike_status AS ENUM ('active', 'appealed', 'revoked');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typnamespace = 'app'::regnamespace AND typname = 'notification_kind') THEN
        CREATE TYPE app.notification_kind AS ENUM (
            'lesson_reminder_1d',
            'lesson_reminder_3h',
            'lesson_changed'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS app.roles (
    id      SERIAL       PRIMARY KEY,
    code    VARCHAR(50)  NOT NULL UNIQUE,
    name    VARCHAR(255) NOT NULL
);

CREATE TABLE IF NOT EXISTS app.users (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    keycloak_user_id  UUID        UNIQUE,
    is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.profiles (
    user_id       UUID         PRIMARY KEY REFERENCES app.users (id) ON DELETE CASCADE,
    last_name     VARCHAR(255) NOT NULL,
    first_name    VARCHAR(255) NOT NULL,
    middle_name   VARCHAR(255),
    role_id       INT          NOT NULL REFERENCES app.roles (id),
    id_curator    UUID         REFERENCES app.users (id) ON DELETE SET NULL,
    phone         VARCHAR(32),
    max_id        BIGINT       UNIQUE,
    status        VARCHAR(50)  NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_profiles_role_id ON app.profiles (role_id);
CREATE INDEX IF NOT EXISTS idx_profiles_id_curator ON app.profiles (id_curator);
CREATE INDEX IF NOT EXISTS idx_profiles_status ON app.profiles (status);

CREATE TABLE IF NOT EXISTS app.groups (
    id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    id_parent   UUID         REFERENCES app.groups (id) ON DELETE SET NULL,
    name        VARCHAR(255) NOT NULL,
    id_hr       UUID         REFERENCES app.users (id) ON DELETE SET NULL,
    status      VARCHAR(50)  NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_groups_id_parent ON app.groups (id_parent);
CREATE INDEX IF NOT EXISTS idx_groups_id_hr ON app.groups (id_hr);
CREATE INDEX IF NOT EXISTS idx_groups_status ON app.groups (status);

CREATE TABLE IF NOT EXISTS app.group_members (
    group_id UUID NOT NULL REFERENCES app.groups (id) ON DELETE CASCADE,
    user_id  UUID NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_group_members_user_id ON app.group_members (user_id);

CREATE TABLE IF NOT EXISTS app.lessons (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id     UUID         NOT NULL REFERENCES app.groups (id) ON DELETE CASCADE,
    teacher_id   UUID         NOT NULL REFERENCES app.users (id) ON DELETE RESTRICT,
    starts_at    TIMESTAMPTZ  NOT NULL,
    ends_at      TIMESTAMPTZ  NOT NULL,
    place        VARCHAR(255),
    lesson_type  VARCHAR(20)  NOT NULL CHECK (lesson_type IN ('lecture', 'practice')),
    CHECK (ends_at > starts_at)
);

CREATE INDEX IF NOT EXISTS idx_lessons_group_id ON app.lessons (group_id);
CREATE INDEX IF NOT EXISTS idx_lessons_teacher_id ON app.lessons (teacher_id);
CREATE INDEX IF NOT EXISTS idx_lessons_starts_at ON app.lessons (starts_at);
CREATE INDEX IF NOT EXISTS idx_lessons_lesson_type ON app.lessons (lesson_type);

CREATE TABLE IF NOT EXISTS app.lesson_members (
    user_id   UUID NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    lesson_id UUID NOT NULL REFERENCES app.lessons (id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, lesson_id)
);

CREATE INDEX IF NOT EXISTS idx_lesson_members_lesson_id ON app.lesson_members (lesson_id);

CREATE TABLE IF NOT EXISTS app.attendance_marks (
    id        UUID                  PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id   UUID                  NOT NULL,
    lesson_id UUID                  NOT NULL,
    status    app.attendance_status NOT NULL,
    marked_by UUID                  NOT NULL REFERENCES app.users (id) ON DELETE RESTRICT,
    marked_at TIMESTAMPTZ           NOT NULL DEFAULT now(),

    FOREIGN KEY (user_id, lesson_id)
        REFERENCES app.lesson_members (user_id, lesson_id)
        ON DELETE CASCADE,

    UNIQUE (user_id, lesson_id)
);

CREATE INDEX IF NOT EXISTS idx_attendance_marks_lesson_id ON app.attendance_marks (lesson_id);
CREATE INDEX IF NOT EXISTS idx_attendance_marks_status ON app.attendance_marks (status);
CREATE INDEX IF NOT EXISTS idx_attendance_marks_marked_by ON app.attendance_marks (marked_by);

CREATE TABLE IF NOT EXISTS app.strikes (
    id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID              NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    lesson_id       UUID              REFERENCES app.lessons (id) ON DELETE SET NULL,
    reason          TEXT              NOT NULL,
    status          app.strike_status NOT NULL DEFAULT 'active',
    strike_number   SMALLINT          NOT NULL CHECK (strike_number BETWEEN 1 AND 3),
    appeal_reason   TEXT,
    appealed_at     TIMESTAMPTZ,
    resolved_by     UUID              REFERENCES app.users (id) ON DELETE SET NULL,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ       NOT NULL DEFAULT now(),

    CONSTRAINT chk_strike_appeal CHECK (
        (status != 'appealed' AND appeal_reason IS NULL AND appealed_at IS NULL)
        OR (status = 'appealed' AND appeal_reason IS NOT NULL AND appealed_at IS NOT NULL)
    ),
    CONSTRAINT chk_strike_revoked CHECK (
        (status != 'revoked' AND resolved_by IS NULL AND resolved_at IS NULL)
        OR (status = 'revoked' AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_strikes_user_id ON app.strikes (user_id);
CREATE INDEX IF NOT EXISTS idx_strikes_lesson_id ON app.strikes (lesson_id);
CREATE INDEX IF NOT EXISTS idx_strikes_status ON app.strikes (status);
CREATE INDEX IF NOT EXISTS idx_strikes_created_at ON app.strikes (created_at);

CREATE TABLE IF NOT EXISTS app.notifications (
    id            UUID                  PRIMARY KEY DEFAULT gen_random_uuid(),
    delivered_to  UUID                  NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
    lesson_id     UUID                  NOT NULL REFERENCES app.lessons (id) ON DELETE CASCADE,
    kind          app.notification_kind NOT NULL,
    sent_at       TIMESTAMPTZ           NOT NULL DEFAULT now(),

    UNIQUE (delivered_to, lesson_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_notifications_delivered_to ON app.notifications (delivered_to);
CREATE INDEX IF NOT EXISTS idx_notifications_lesson_id ON app.notifications (lesson_id);
CREATE INDEX IF NOT EXISTS idx_notifications_sent_at ON app.notifications (sent_at);

INSERT INTO app.roles (code, name) VALUES
    ('employee', 'Сотрудник'),
    ('teacher', 'Преподаватель'),
    ('curator', 'Куратор'),
    ('hr', 'HR'),
    ('admin', 'Администратор')
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name;
