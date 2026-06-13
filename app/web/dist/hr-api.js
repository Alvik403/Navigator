(function (global) {
  "use strict";

  var api = global.MaxRassApi;

  var UI_ROLES = [
    { id: "admin", code: "admin", name: "Администратор" },
    { id: "hr", code: "hr", name: "HR" },
    { id: "teacher", code: "teacher", name: "Преподаватель" },
    { id: "student", code: "student", name: "Ученик" },
    { id: "curator", code: "curator", name: "Куратор" },
  ];

  var ROLE_API_TO_UI = {
    employee: "student",
    teacher: "teacher",
    curator: "curator",
    hr: "hr",
    admin: "admin",
  };

  var store = {
    me: null,
    users: [],
    groups: [],
    groupMembers: [],
    teachersMeta: [],
    attendanceByUser: {},
    attendanceIssues: {},
    notifications: [],
    summaryReport: null,
    strikes: [],
    appeals: [],
    lessons: [],
  };

  function uiRoleCode(apiCode) {
    return ROLE_API_TO_UI[apiCode] || apiCode;
  }

  function apiRoleCode(uiCode) {
    if (uiCode === "student") return "employee";
    return uiCode;
  }

  function mapUser(row) {
    var code = uiRoleCode(row.role_code);
    return {
      id: row.id,
      firstName: row.first_name,
      lastName: row.last_name,
      middleName: row.middle_name || null,
      id_max: row.max_id != null ? String(row.max_id) : null,
      phone: row.phone || null,
      id_role: code,
      status: row.status === "inactive" ? "inactive" : "active",
      ban_reason: row.ban_reason || null,
      id_curator: row.id_curator || null,
      strikes: row.strike_count || 0,
    };
  }

  function mapGroup(row) {
    return {
      id: row.id,
      id_parent: row.id_parent || null,
      name: row.name,
      id_hr: row.id_hr,
      createdAt: row.created_at ? String(row.created_at).slice(0, 10) : "",
      status: row.status || "active",
      members: row.members || [],
    };
  }

  function mapStrike(row) {
    return {
      id: row.id,
      user_id: row.user_id,
      lesson_id: row.lesson_id,
      reason: row.reason,
      status: row.status,
      strike_number: row.strike_number,
      appeal_reason: row.appeal_reason,
      appealed_at: row.appealed_at,
      resolved_by: row.resolved_by,
      resolved_at: row.resolved_at,
      created_at: row.created_at,
      last_name: row.last_name,
      first_name: row.first_name,
      group_name: row.group_name,
    };
  }

  function mapLesson(row) {
    var d = row.starts_at ? new Date(row.starts_at) : null;
    return {
      id: row.id,
      group_id: row.group_id,
      group_name: row.group_name,
      teacher_id: row.teacher_id,
      teacher_name: row.teacher_name || [row.teacher_last_name, row.teacher_first_name].filter(Boolean).join(" "),
      starts_at: row.starts_at,
      ends_at: row.ends_at,
      place: row.place || null,
      lesson_type: row.lesson_type,
      title: row.lesson_title || row.title || (row.lesson_type === "practice" ? "Практика" : "Лекция"),
      date: d ? d.toISOString().slice(0, 10) : "—",
      time: d ? d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "",
    };
  }

  function groupTeachersFromLessons(groupId) {
    var seen = {};
    var result = [];
    store.lessons.forEach(function (l) {
      if (l.group_id !== groupId || seen[l.teacher_id]) return;
      seen[l.teacher_id] = true;
      var t = userById(l.teacher_id);
      result.push({
        id: l.teacher_id,
        name: l.teacher_name || fullName(t),
      });
    });
    return result;
  }

  function rebuildGroupMembers(groups) {
    var members = [];
    groups.forEach(function (g) {
      (g.members || []).forEach(function (m) {
        if (uiRoleCode(m.role_code) === "student") {
          members.push({ id_group: g.id, id_user: m.id, type: "student" });
        }
      });
    });
    return members;
  }

  function fullName(u) {
    if (!u) return "—";
    return [u.firstName, u.lastName].filter(Boolean).join(" ");
  }

  function userById(id) {
    return store.users.find(function (u) { return u.id === id; });
  }

  function usersByRole(code) {
    return store.users.filter(function (u) { return u.id_role === code; });
  }

  function courses() {
    return store.groups.filter(function (g) { return !g.id_parent; });
  }

  function workingGroups(parentId) {
    return store.groups.filter(function (g) { return g.id_parent === parentId; });
  }

  function allWorkingGroups() {
    return store.groups.filter(function (g) { return g.id_parent; });
  }

  function groupStudents(groupId) {
    return store.groupMembers
      .filter(function (m) { return m.id_group === groupId && m.type === "student"; })
      .map(function (m) { return userById(m.id_user); })
      .filter(Boolean);
  }

  function studentGroups(studentId) {
    return store.groupMembers
      .filter(function (m) { return m.id_user === studentId && m.type === "student"; })
      .map(function (m) { return store.groups.find(function (g) { return g.id === m.id_group; }); })
      .filter(Boolean);
  }

  function studentWorkGroup(studentId) {
    var list = studentGroups(studentId);
    return list.length ? list[0] : null;
  }

  function courseOfGroup(groupId) {
    var g = store.groups.find(function (x) { return x.id === groupId; });
    if (!g) return null;
    if (!g.id_parent) return g;
    return store.groups.find(function (x) { return x.id === g.id_parent; });
  }

  function teacherDirectionsFromMeta(teacherId) {
    var meta = store.teachersMeta.find(function (t) { return t.id === teacherId; });
    if (!meta || !meta.groups) return [];
    var names = meta.groups.filter(function (g) { return !g.id_parent; }).map(function (g) { return g.name; });
    return names.filter(function (v, i, a) { return a.indexOf(v) === i; });
  }

  function teacherWorkGroupsFromMeta(teacherId) {
    var meta = store.teachersMeta.find(function (t) { return t.id === teacherId; });
    if (!meta || !meta.groups) return [];
    var names = meta.groups.filter(function (g) { return g.id_parent; }).map(function (g) { return g.name; });
    return names.filter(function (v, i, a) { return a.indexOf(v) === i; });
  }

  function lessonTitle(item) {
    return item.lesson_title || item.title || (item.lesson_type === "practice" ? "Практика" : "Лекция");
  }

  function studentAttendanceStats(studentId) {
    var rows = store.attendanceByUser[studentId] || [];
    var issues = store.attendanceIssues[studentId] || [];
    var total = 0;
    var present = 0;
    var late = 0;
    var absent = 0;
    rows.forEach(function (r) {
      total += r.lessons_total || 0;
      present += r.present_count || 0;
      late += r.late_count || 0;
      absent += r.absent_count || 0;
    });
    var attended = present + late;
    return {
      total: total,
      attended: attended,
      late: late,
      absent: absent,
      issues: issues.map(function (item) {
        var d = item.starts_at ? new Date(item.starts_at) : null;
        return {
          mark: { mark: item.attendance_status },
          lesson: {
            title: lessonTitle(item),
            date: d ? d.toISOString().slice(0, 10) : "—",
            time: d ? d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }) : "",
            place: item.place || "",
          },
          group: { name: item.group_name || "—" },
        };
      }),
    };
  }

  async function loadAttendanceIssues(userIds) {
    var map = {};
    await Promise.all(userIds.map(async function (uid) {
      try {
        var res = await api.get("/hr/attendance/users/" + uid + "/issues");
        map[uid] = res.items || [];
      } catch (_e) {
        map[uid] = [];
      }
    }));
    store.attendanceIssues = map;
  }

  async function reloadCore() {
    var meRes = await api.get("/auth/me");
    store.me = meRes.profile || meRes;

    var results = await Promise.all([
      api.get("/hr/users?role=employee"),
      api.get("/hr/users?role=teacher"),
      api.get("/hr/users?role=curator"),
      api.get("/hr/users?role=hr"),
      api.get("/hr/groups"),
      api.get("/hr/teachers"),
      api.get("/hr/reports/attendance/users"),
      api.get("/hr/notifications"),
      api.get("/hr/reports/summary"),
      api.get("/hr/strikes"),
      api.get("/hr/appeals"),
      api.get("/hr/lessons"),
    ]);

    var employees = (results[0].items || []).map(mapUser);
    var teachers = (results[1].items || []).map(mapUser);
    var curators = (results[2].items || []).map(mapUser);
    var hrs = (results[3].items || []).map(mapUser);
    store.users = employees.concat(teachers, curators, hrs);
    if (store.me && !store.users.some(function (u) { return u.id === store.me.id; })) {
      store.users.push(mapUser(store.me));
    }

    store.groups = (results[4].items || []).map(mapGroup);
    store.groupMembers = rebuildGroupMembers(store.groups);
    store.teachersMeta = results[5].items || [];

    var attRows = results[6].items || [];
    store.attendanceByUser = {};
    attRows.forEach(function (row) {
      var uid = row.user_id;
      if (!store.attendanceByUser[uid]) store.attendanceByUser[uid] = [];
      store.attendanceByUser[uid].push(row);
    });

    store.notifications = (results[7].items || []).map(function (n, i) {
      return {
        id: n.id || String(i),
        id_user: n.delivered_to || n.user_id,
        type: n.type || n.kind,
        category: n.category || "lesson",
        source: n.source || "db",
        text: n.text,
        read: false,
        created_at: n.sent_at,
      };
    });

    store.summaryReport = results[8] || null;
    store.strikes = (results[9].items || []).map(mapStrike);
    store.appeals = (results[10].items || []).map(mapStrike);
    store.lessons = (results[11].items || []).map(mapLesson);

    var studentIds = employees.map(function (u) { return u.id; });
    await loadAttendanceIssues(studentIds.slice(0, 50));
  }

  function buildAppData() {
    var hrProfile = store.me ? mapUser(store.me) : null;
    return {
      roles: UI_ROLES,
      users: store.users,
      groups: store.groups,
      groupMembers: store.groupMembers,
      lessons: store.lessons,
      marks: [],
      strikes: store.strikes,
      appeals: store.appeals,
      notifications: store.notifications,
      summaryReport: store.summaryReport,
      session: { hrId: hrProfile ? hrProfile.id : null },
      fullName: fullName,
      userById: userById,
      usersByRole: usersByRole,
      courses: courses,
      workingGroups: workingGroups,
      allWorkingGroups: allWorkingGroups,
      groupStudents: groupStudents,
      studentGroups: studentGroups,
      studentWorkGroup: studentWorkGroup,
      courseOfGroup: courseOfGroup,
      teacherDirectionsFromMeta: teacherDirectionsFromMeta,
      teacherWorkGroupsFromMeta: teacherWorkGroupsFromMeta,
      groupTeachersFromLessons: groupTeachersFromLessons,
      studentAttendanceStats: studentAttendanceStats,
      teachersForHr: function () {
        if (!store.teachersMeta.length) {
          return store.users.filter(function (u) { return u.id_role === "teacher"; });
        }
        var ids = store.teachersMeta.map(function (t) { return t.id; });
        return store.users.filter(function (u) {
          return u.id_role === "teacher" && ids.indexOf(u.id) >= 0;
        });
      },
      roleById: function (id) { return UI_ROLES.find(function (r) { return r.id === id; }); },
      roleCode: function (id) { return UI_ROLES.find(function (r) { return r.id === id; })?.code || ""; },
      statusLabel: { active: "активен", inactive: "не активен" },
      markLabel: { present: "был", absent: "не был", late: "опоздал" },
      lessonTypeLabel: { lecture: "лекция", practice: "практика" },
    };
  }

  function parseFio(fio) {
    var parts = String(fio || "").trim().split(/\s+/);
    var lastName = parts.pop() || "";
    var firstName = parts.join(" ") || "";
    return { firstName: firstName, lastName: lastName };
  }

  async function bootstrap() {
    await reloadCore();
    return buildAppData();
  }

  async function refresh() {
    await reloadCore();
    return buildAppData();
  }

  function buildUserPatchBody(patch) {
    var body = {};
    if (patch.firstName != null) body.first_name = patch.firstName;
    if (patch.lastName != null) body.last_name = patch.lastName;
    if (patch.middleName != null) body.middle_name = patch.middleName || null;
    if (patch.phone != null) body.phone = patch.phone || null;
    if (patch.status != null) body.status = patch.status;
    if (patch.ban_reason != null) body.ban_reason = patch.ban_reason;
    if (patch.id_curator === null || patch.id_curator === "") body.clear_id_curator = true;
    else if (patch.id_curator != null) body.id_curator = patch.id_curator;
    if (patch.max_id != null) body.max_id = patch.max_id ? parseInt(patch.max_id, 10) : null;
    if (patch.roleCode != null) body.role_code = apiRoleCode(patch.roleCode);
    return body;
  }

  async function updateUser(id, patch) {
    return api.patch("/hr/users/" + id, buildUserPatchBody(patch));
  }

  async function updateStudent(id, patch) {
    return updateUser(id, patch);
  }

  async function createUsersBulk(rows, roleUiCode) {
    var normalized = (global.HrFields && global.HrFields.normalizeRows)
      ? global.HrFields.normalizeRows(rows)
      : rows;
    var items = normalized.map(function (row) {
      var lastName = String(row.last_name || "").trim();
      var firstName = String(row.first_name || "").trim();
      var middleName = String(row.middle_name || "").trim();
      if ((!lastName || !firstName) && row.fio) {
        var parts = (global.HrFields && global.HrFields.parseFioParts)
          ? global.HrFields.parseFioParts(row.fio)
          : parseFio(row.fio);
        lastName = lastName || parts.last_name || parts.lastName || "";
        firstName = firstName || parts.first_name || parts.firstName || "";
        middleName = middleName || parts.middle_name || "";
      }
      var status = String(row.status || "").toLowerCase();
      var inactive = ["inactive", "не активен", "неактивен"].includes(status);
      return {
        last_name: lastName,
        first_name: firstName,
        middle_name: middleName || null,
        role_code: apiRoleCode(roleUiCode),
        phone: row.phone || null,
        max_id: row.id_max ? parseInt(row.id_max, 10) : null,
        status: inactive ? "inactive" : "active",
        id_curator: row.id_curator || null,
      };
    }).filter(function (r) { return r.last_name && r.first_name; });
    if (!items.length) {
      throw new Error("Укажите хотя бы одного пользователя с фамилией и именем");
    }
    return api.post("/hr/users/bulk", { items: items });
  }

  async function bulkAddGroupMembers(groupId, userIds) {
    return api.post("/hr/groups/" + groupId + "/members/bulk", { user_ids: userIds });
  }

  async function addStrike(userId, reason) {
    return api.post("/hr/users/" + userId + "/strikes", { reason: reason || "manual" });
  }

  async function revokeStrike(userId, comment) {
    return api.post("/hr/users/" + userId + "/strikes/revoke", { comment: comment || "снят HR" });
  }

  async function resolveAppeal(strikeId, approved) {
    return api.post("/hr/appeals/" + strikeId + "/resolve", { approved: approved });
  }

  async function patchUserStatus(userId, status, banReason) {
    var body = { status: status };
    if (status === "inactive" && banReason) body.ban_reason = banReason;
    return api.patch("/hr/users/" + userId, body);
  }

  async function createGroup(data) {
    return api.post("/hr/groups", data);
  }

  async function updateGroup(id, data) {
    return api.patch("/hr/groups/" + id, data);
  }

  async function syncGroupMembers(groupId, studentIds) {
    var group = store.groups.find(function (g) { return g.id === groupId; });
    var current = group ? (group.members || []).filter(function (m) {
      return uiRoleCode(m.role_code) === "student";
    }).map(function (m) { return m.id; }) : [];
    var toAdd = studentIds.filter(function (id) { return current.indexOf(id) < 0; });
    var toRemove = current.filter(function (id) { return studentIds.indexOf(id) < 0; });
    for (var i = 0; i < toRemove.length; i++) {
      await api.del("/hr/groups/" + groupId + "/members/" + toRemove[i]);
    }
    if (toAdd.length) {
      await bulkAddGroupMembers(groupId, toAdd);
    }
  }

  async function listLessons(groupId) {
    var q = groupId ? "?group_id=" + encodeURIComponent(groupId) : "";
    var res = await api.get("/hr/lessons" + q);
    return (res.items || []).map(mapLesson);
  }

  async function createLesson(data) {
    return api.post("/hr/lessons", data);
  }

  global.HrApi = {
    bootstrap: bootstrap,
    refresh: refresh,
    updateUser: updateUser,
    updateStudent: updateStudent,
    createUsersBulk: createUsersBulk,
    bulkAddGroupMembers: bulkAddGroupMembers,
    addStrike: addStrike,
    revokeStrike: revokeStrike,
    resolveAppeal: resolveAppeal,
    patchUserStatus: patchUserStatus,
    createGroup: createGroup,
    updateGroup: updateGroup,
    syncGroupMembers: syncGroupMembers,
    listLessons: listLessons,
    createLesson: createLesson,
    parseFio: parseFio,
    apiRoleCode: apiRoleCode,
  };
})(window);
