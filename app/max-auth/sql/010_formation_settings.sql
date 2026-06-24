-- Per-track formation policy and slot binding.

ALTER TABLE app.tracks
    ADD COLUMN IF NOT EXISTS formation_auto_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS formation_max_members INT NOT NULL DEFAULT 12 CHECK (formation_max_members BETWEEN 1 AND 50),
    ADD COLUMN IF NOT EXISTS formation_min_members INT NOT NULL DEFAULT 1 CHECK (formation_min_members BETWEEN 1 AND 50),
    ADD COLUMN IF NOT EXISTS formation_lock_days INT NOT NULL DEFAULT 14 CHECK (formation_lock_days >= 0),
    ADD COLUMN IF NOT EXISTS formation_weight_penalty NUMERIC(8, 2) NOT NULL DEFAULT 50 CHECK (formation_weight_penalty >= 0),
    ADD COLUMN IF NOT EXISTS formation_lesson_type VARCHAR(20) NOT NULL DEFAULT 'practice'
        CHECK (formation_lesson_type IN ('lecture', 'practice')),
    ADD COLUMN IF NOT EXISTS formation_default_place VARCHAR(255);

CREATE TABLE IF NOT EXISTS app.track_formation_slots (
    track_id UUID NOT NULL REFERENCES app.tracks (id) ON DELETE CASCADE,
    slot_id  UUID NOT NULL REFERENCES app.conveyor_slots (id) ON DELETE CASCADE,
    PRIMARY KEY (track_id, slot_id)
);

CREATE INDEX IF NOT EXISTS idx_track_formation_slots_slot ON app.track_formation_slots (slot_id);
