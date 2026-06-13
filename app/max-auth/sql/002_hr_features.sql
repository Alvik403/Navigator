-- HR dashboard: ban reason, lesson titles

ALTER TABLE app.profiles
    ADD COLUMN IF NOT EXISTS ban_reason VARCHAR(255);

ALTER TABLE app.lessons
    ADD COLUMN IF NOT EXISTS title VARCHAR(255);
