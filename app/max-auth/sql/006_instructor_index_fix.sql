-- Fix: allow one instructor on multiple reporting groups (1 instructor per group, not globally unique).
DROP INDEX IF EXISTS app.idx_groups_instructor_unique;
CREATE INDEX IF NOT EXISTS idx_groups_instructor_id ON app.groups (instructor_id);
