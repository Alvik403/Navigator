-- СМУ-1 … СМУ-13: короткие названия без (2/2) и т.п.

INSERT INTO app.smu_patterns (code, name, work_days, off_days, anchor_date)
VALUES
    ('smu-1',  'СМУ-1',  2, 2, DATE '2026-01-01'),
    ('smu-2',  'СМУ-2',  2, 2, DATE '2026-01-02'),
    ('smu-3',  'СМУ-3',  2, 2, DATE '2026-01-03'),
    ('smu-4',  'СМУ-4',  2, 2, DATE '2026-01-04'),
    ('smu-5',  'СМУ-5',  2, 2, DATE '2026-01-05'),
    ('smu-6',  'СМУ-6',  2, 2, DATE '2026-01-06'),
    ('smu-7',  'СМУ-7',  2, 2, DATE '2026-01-07'),
    ('smu-8',  'СМУ-8',  2, 2, DATE '2026-01-08'),
    ('smu-9',  'СМУ-9',  2, 2, DATE '2026-01-09'),
    ('smu-10', 'СМУ-10', 2, 2, DATE '2026-01-10'),
    ('smu-11', 'СМУ-11', 2, 2, DATE '2026-01-11'),
    ('smu-12', 'СМУ-12', 2, 2, DATE '2026-01-12'),
    ('smu-13', 'СМУ-13', 2, 2, DATE '2026-01-13')
ON CONFLICT (code) DO UPDATE SET
    name = EXCLUDED.name,
    work_days = EXCLUDED.work_days,
    off_days = EXCLUDED.off_days,
    anchor_date = EXCLUDED.anchor_date,
    status = 'active',
    updated_at = now();
