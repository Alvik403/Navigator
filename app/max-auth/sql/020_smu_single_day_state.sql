-- SMU: один статус на день (день / ночь / доп / выходной).

ALTER TABLE app.smu_pattern_day_overrides
    ALTER COLUMN state TYPE VARCHAR(32);

ALTER TABLE app.smu_pattern_day_overrides
    DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_state_check;

UPDATE app.smu_pattern_day_overrides SET state = 'day' WHERE state = 'work' AND period = 'day';
UPDATE app.smu_pattern_day_overrides SET state = 'night' WHERE state = 'work' AND period = 'night';
UPDATE app.smu_pattern_day_overrides SET state = 'extra_day' WHERE state = 'extra' AND period = 'day';
UPDATE app.smu_pattern_day_overrides SET state = 'extra_night' WHERE state = 'extra' AND period = 'night';

UPDATE app.smu_pattern_day_overrides d
SET state = CASE
    WHEN n.state IN ('extra_night', 'extra_day') THEN n.state
    WHEN n.state IN ('night', 'extra_night') AND d.state = 'off' THEN n.state
    WHEN d.state = 'off' AND n.state <> 'off' THEN n.state
    ELSE d.state
END
FROM app.smu_pattern_day_overrides n
WHERE d.smu_pattern_id = n.smu_pattern_id
  AND d.shift_date = n.shift_date
  AND d.shift_number = n.shift_number
  AND d.period = 'day'
  AND n.period = 'night';

DELETE FROM app.smu_pattern_day_overrides WHERE period = 'night';

UPDATE app.smu_pattern_day_overrides SET period = 'day' WHERE period IS DISTINCT FROM 'day';

ALTER TABLE app.smu_pattern_day_overrides
    DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_pattern_date_shift_period_key;

DROP INDEX IF EXISTS app.uq_smu_pattern_overrides_period;

-- Убрать возможные дубли перед UNIQUE (повторный прогон / частично применённые миграции).
DELETE FROM app.smu_pattern_day_overrides d
USING app.smu_pattern_day_overrides keeper
WHERE d.smu_pattern_id = keeper.smu_pattern_id
  AND d.shift_date = keeper.shift_date
  AND d.shift_number = keeper.shift_number
  AND d.id <> keeper.id
  AND (
      keeper.updated_at > d.updated_at
      OR (keeper.updated_at = d.updated_at AND keeper.created_at > d.created_at)
      OR (keeper.updated_at = d.updated_at AND keeper.created_at = d.created_at AND keeper.id > d.id)
  );

CREATE UNIQUE INDEX IF NOT EXISTS uq_smu_pattern_overrides_shift
    ON app.smu_pattern_day_overrides (smu_pattern_id, shift_date, shift_number);

ALTER TABLE app.smu_pattern_day_overrides
    DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_state_check;

ALTER TABLE app.smu_pattern_day_overrides
    ADD CONSTRAINT smu_pattern_day_overrides_state_check
        CHECK (state IN ('day', 'night', 'extra_day', 'extra_night', 'off'));
