-- Audit log: who did what, when; snapshots for restore after delete.

CREATE TABLE IF NOT EXISTS app.audit_log (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id   UUID         REFERENCES app.users (id) ON DELETE SET NULL,
    actor_name      VARCHAR(512),
    action          VARCHAR(50)  NOT NULL,
    entity_type     VARCHAR(80)  NOT NULL,
    entity_id       VARCHAR(255),
    entity_label    TEXT,
    payload         JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    restored_at     TIMESTAMPTZ,
    restored_by     UUID         REFERENCES app.users (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON app.audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON app.audit_log (actor_user_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON app.audit_log (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON app.audit_log (action);
CREATE INDEX IF NOT EXISTS idx_audit_log_restored ON app.audit_log (restored_at) WHERE restored_at IS NULL;
