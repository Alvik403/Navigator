-- Разрешить state = 'extra' в ручных правках графика СМУ (legacy, до 020).
-- Не переустанавливать старый CHECK, если уже применена миграция 020 (day/night/...).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM app.smu_pattern_day_overrides
        WHERE state IN ('day', 'night', 'extra_day', 'extra_night')
    ) THEN
        RETURN;
    END IF;

    ALTER TABLE app.smu_pattern_day_overrides
        DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_state_check;

    ALTER TABLE app.smu_pattern_day_overrides
        ADD CONSTRAINT smu_pattern_day_overrides_state_check
            CHECK (state IN ('work', 'off', 'extra'));
END $$;
