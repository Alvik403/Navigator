-- SMU: отдельные отметки для дневной и ночной половины ячейки.
-- Пропускается, если уже применена миграция 020 (один статус на день).

DO $$
DECLARE
    r record;
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'app'
          AND indexname = 'uq_smu_pattern_overrides_shift'
    ) THEN
        RETURN;
    END IF;

    ALTER TABLE app.smu_pattern_day_overrides
        ADD COLUMN IF NOT EXISTS period VARCHAR(10) NOT NULL DEFAULT 'day';

    ALTER TABLE app.smu_pattern_day_overrides
        DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_period_check;

    ALTER TABLE app.smu_pattern_day_overrides
        ADD CONSTRAINT smu_pattern_day_overrides_period_check
            CHECK (period IN ('day', 'night'));

    ALTER TABLE app.smu_pattern_day_overrides
        DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_smu_pattern_id_shift_date_shift_number_key;

    ALTER TABLE app.smu_pattern_day_overrides
        DROP CONSTRAINT IF EXISTS smu_pattern_day_overrides_smu_pattern_id_shift_date_shift_n_key;

    FOR r IN
        SELECT con.conname
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = 'app'
          AND rel.relname = 'smu_pattern_day_overrides'
          AND con.contype = 'u'
          AND pg_get_constraintdef(con.oid) NOT LIKE '%period%'
    LOOP
        EXECUTE format(
            'ALTER TABLE app.smu_pattern_day_overrides DROP CONSTRAINT IF EXISTS %I',
            r.conname
        );
    END LOOP;

    INSERT INTO app.smu_pattern_day_overrides (smu_pattern_id, shift_date, shift_number, state, note, period)
    SELECT d.smu_pattern_id, d.shift_date, d.shift_number, d.state, d.note, 'night'
    FROM app.smu_pattern_day_overrides d
    WHERE d.period = 'day'
      AND NOT EXISTS (
          SELECT 1
          FROM app.smu_pattern_day_overrides n
          WHERE n.smu_pattern_id = d.smu_pattern_id
            AND n.shift_date = d.shift_date
            AND n.shift_number = d.shift_number
            AND n.period = 'night'
      );

    CREATE UNIQUE INDEX IF NOT EXISTS uq_smu_pattern_overrides_period
        ON app.smu_pattern_day_overrides (smu_pattern_id, shift_date, shift_number, period);
END $$;
