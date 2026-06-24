-- Standard formation time slots for track settings (12:00–15:00).

INSERT INTO app.conveyor_slots (code, name, starts_at_local, duration_min, sort_order)
VALUES
    ('slot-12-00', '12:00', '12:00', 60, 30),
    ('slot-13-00', '13:00', '13:00', 60, 40),
    ('slot-14-00', '14:00', '14:00', 60, 50),
    ('slot-15-00', '15:00', '15:00', 60, 60)
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    starts_at_local = EXCLUDED.starts_at_local,
    duration_min = EXCLUDED.duration_min,
    sort_order = EXCLUDED.sort_order,
    status = 'active',
    updated_at = now();
