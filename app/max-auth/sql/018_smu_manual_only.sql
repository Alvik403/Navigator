-- SMU: allow manual-only patterns (no cycle formula).

ALTER TABLE app.smu_patterns DROP CONSTRAINT IF EXISTS smu_patterns_work_days_check;

ALTER TABLE app.smu_patterns
    ADD CONSTRAINT smu_patterns_work_days_check CHECK (work_days >= 0);

ALTER TABLE app.smu_patterns ALTER COLUMN work_days SET DEFAULT 0;
ALTER TABLE app.smu_patterns ALTER COLUMN off_days SET DEFAULT 0;
