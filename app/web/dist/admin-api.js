(function (global) {
  "use strict";

  var api = global.MaxRassApi;

  var ROLE_LABELS = {
    admin: "Администратор",
    hr: "HR",
    teacher: "Преподаватель",
    curator: "Куратор",
    employee: "Ученик",
  };

  var WEB_ROLES = { admin: true, hr: true, teacher: true };

  function fullName(row) {
    return [row.last_name, row.first_name, row.middle_name].filter(Boolean).join(" ");
  }

  function roleLabel(code) {
    return ROLE_LABELS[code] || code || "—";
  }

  async function loadUsers(role) {
    var path = role ? "/admin/users?role=" + encodeURIComponent(role) : "/admin/users";
    var res = await api.get(path);
    return res.items || [];
  }

  async function loadRoles() {
    var res = await api.get("/admin/roles");
    return res.items || [];
  }

  async function createUser(body) {
    return api.post("/admin/users", body);
  }

  async function updateUser(id, body) {
    return api.patch("/admin/users/" + id, body);
  }

  async function linkKeycloak(id, username) {
    return api.post("/admin/users/" + id + "/keycloak/link", { username: username });
  }

  async function createKeycloak(id, body) {
    return api.post("/admin/users/" + id + "/keycloak/create", body);
  }

  async function resetKeycloakPassword(id, password, temporary) {
    return api.post("/admin/users/" + id + "/keycloak/reset-password", {
      password: password || null,
      temporary: !!temporary,
    });
  }

  async function loadAuditMeta() {
    return api.get("/admin/audit-log/meta");
  }

  async function loadAuditLog(params) {
    var q = new URLSearchParams();
    if (params.actor_user_id) q.set("actor_user_id", params.actor_user_id);
    if (params.action) q.set("action", params.action);
    if (params.entity_type) q.set("entity_type", params.entity_type);
    if (params.restorable_only) q.set("restorable_only", "true");
    if (params.limit) q.set("limit", String(params.limit));
    if (params.offset) q.set("offset", String(params.offset));
    var suffix = q.toString() ? "?" + q.toString() : "";
    var res = await api.get("/admin/audit-log" + suffix);
    return res.items || [];
  }

  async function restoreAuditEntry(entryId) {
    return api.post("/admin/audit-log/" + entryId + "/restore", {});
  }

  global.AdminApi = {
    ROLE_LABELS: ROLE_LABELS,
    WEB_ROLES: WEB_ROLES,
    fullName: fullName,
    roleLabel: roleLabel,
    loadUsers: loadUsers,
    loadRoles: loadRoles,
    createUser: createUser,
    updateUser: updateUser,
    linkKeycloak: linkKeycloak,
    createKeycloak: createKeycloak,
    resetKeycloakPassword: resetKeycloakPassword,
    loadAuditMeta: loadAuditMeta,
    loadAuditLog: loadAuditLog,
    restoreAuditEntry: restoreAuditEntry,
  };
})(window);
