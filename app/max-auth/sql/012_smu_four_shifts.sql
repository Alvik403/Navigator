-- 4 смены на СМУ, ручной график и допсмены на уровне паттерна.

CREATE TABLE IF NOT EXISTS app.smu_pattern_day_overrides (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    smu_pattern_id   UUID        NOT NULL REFERENCES app.smu_patterns (id) ON DELETE CASCADE,
    shift_date       DATE        NOT NULL,
    shift_number     SMALLINT    NOT NULL CHECK (shift_number BETWEEN 1 AND 4),
    state            VARCHAR(20) NOT NULL CHECK (state IN ('work', 'off', 'extra')),
    note             TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (smu_pattern_id, shift_date, shift_number)
);

CREATE INDEX IF NOT EXISTS idx_smu_pattern_overrides_pattern_date
    ON app.smu_pattern_day_overrides (smu_pattern_id, shift_date);

ALTER TABLE app.smu_pattern_day_overrides
    DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_shift_number_check;

ALTER TABLE app.smu_pattern_day_overrides
    ADD CONSTRAINT smu_pattern_day_overrides_shift_number_check
        CHECK (shift_number BETWEEN 1 AND 4);

ALTER TABLE app.smu_patterns
    ADD COLUMN IF NOT EXISTS shift_count SMALLINT NOT NULL DEFAULT 4 CHECK (shift_count BETWEEN 1 AND 4),
    ADD COLUMN IF NOT EXISTS target_shift3 INT CHECK (target_shift3 IS NULL OR target_shift3 >= 0),
    ADD COLUMN IF NOT EXISTS target_shift4 INT CHECK (target_shift4 IS NULL OR target_shift4 >= 0);

ALTER TABLE app.user_smu DROP CONSTRAINT IF EXISTS user_smu_shift_number_check;
ALTER TABLE app.user_smu
    ADD CONSTRAINT user_smu_shift_number_check CHECK (shift_number BETWEEN 1 AND 4);

ALTER TABLE app.smu_extra_shifts DROP CONSTRAINT IF EXISTS smu_extra_shifts_shift_number_check;
ALTER TABLE app.smu_extra_shifts
    ADD CONSTRAINT smu_extra_shifts_shift_number_check CHECK (shift_number BETWEEN 1 AND 4);
