-- SMU brigade shifts: shift 1 and shift 2 within one pattern (offset by work_days).

ALTER TABLE app.user_smu
    ADD COLUMN IF NOT EXISTS shift_number SMALLINT NOT NULL DEFAULT 1 CHECK (shift_number IN (1, 2));

CREATE INDEX IF NOT EXISTS idx_user_smu_shift ON app.user_smu (smu_pattern_id, shift_number);
