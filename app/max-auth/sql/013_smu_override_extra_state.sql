-- Разрешить state = 'extra' в ручных правках графика СМУ.
-- Таблица могла быть создана до 012 с CHECK (work, off) only.

ALTER TABLE app.smu_pattern_day_overrides
    DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_state_check;

ALTER TABLE app.smu_pattern_day_overrides
    ADD CONSTRAINT smu_pattern_day_overrides_state_check
        CHECK (state IN ('work', 'off', 'extra'));
