-- Разрешить смены 3 и 4 в ручных правках графика СМУ.
-- Таблица могла быть создана до 012 с CHECK (shift_number IN (1, 2)).

ALTER TABLE app.smu_pattern_day_overrides
    DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_shift_number_check;

ALTER TABLE app.smu_pattern_day_overrides
    ADD CONSTRAINT smu_pattern_day_overrides_shift_number_check
        CHECK (shift_number BETWEEN 1 AND 4);
