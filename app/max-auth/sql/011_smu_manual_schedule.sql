-- Manual SMU schedule: day/night targets and extra shift binding.

ALTER TABLE app.smu_patterns
    ADD COLUMN IF NOT EXISTS target_shift1 INT CHECK (target_shift1 IS NULL OR target_shift1 >= 0),
    ADD COLUMN IF NOT EXISTS target_shift2 INT CHECK (target_shift2 IS NULL OR target_shift2 >= 0);

ALTER TABLE app.smu_extra_shifts
    ADD COLUMN IF NOT EXISTS shift_number SMALLINT NOT NULL DEFAULT 1 CHECK (shift_number IN (1, 2));

CREATE INDEX IF NOT EXISTS idx_smu_extra_shifts_shift ON app.smu_extra_shifts (shift_date, shift_number);
