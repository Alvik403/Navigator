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
    teachersMeta: [],
    attendanceByUser: {},
    attendanceIssues: {},
    notifications: [],
    summaryReport: null,
    strikes: [],
    appeals: [],
    lessons: [],
    tracks: [],
    conveyorSlots: [],
    smuPatterns: [],
    smuAssignments: [],
    smuExtraShifts: [],
    smuOverrides: {},
    trackAssignments: {},
    instructorTracks: {},
    trackTeacherLinks: [],
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
      track_name: row.track_name,
      group_name: row.group_name,
    };
  }

  function mapLesson(row) {
    var d = row.starts_at ? new Date(row.starts_at) : null;
    return {
      id: row.id,
      track_id: row.track_id || null,
      track_name: row.track_name || null,
      slot_id: row.slot_id || null,
      slot_name: row.slot_name || null,
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

  function mapTrack(row) {
    return {
      id: row.id,
      code: row.code,
      name: row.name,
      description: row.description || "",
      practice_required: row.practice_required || 0,
      lecture_required: row.lecture_required || 0,
      completion_days: row.completion_days || 90,
      status: row.status || "active",
    };
  }

  function mapSmuPattern(row) {
    return {
      id: row.id,
      code: row.code,
      name: row.name,
      work_days: row.work_days,
      off_days: row.off_days,
      anchor_date: row.anchor_date ? String(row.anchor_date).slice(0, 10) : "",
      status: row.status || "active",
    };
  }

  function mapConveyorSlot(row) {
    return {
      id: row.id,
      code: row.code,
      name: row.name,
      starts_at_local: row.starts_at_local ? String(row.starts_at_local).slice(0, 5) : "",
      duration_min: row.duration_min || 60,
      sort_order: row.sort_order || 0,
      status: row.status || "active",
    };
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

  function studentTracks(studentId) {
    var result = [];
    store.tracks.forEach(function (t) {
      var assignments = store.trackAssignments[t.id] || [];
      if (assignments.some(function (a) { return a.user_id === studentId && (a.status || "active") === "active"; })) {
        result.push(t);
      }
    });
    return result;
  }

  function studentPrimaryTrack(studentId) {
    var list = studentTracks(studentId);
    return list.length ? list[0] : null;
  }

  function teacherTracksFromMeta(teacherId) {
    var meta = store.teachersMeta.find(function (t) { return t.id === teacherId; });
    if (!meta || !meta.tracks) return [];
    return meta.tracks.map(function (t) { return t.name; }).filter(Boolean);
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
          track: { name: item.track_name || item.group_name || "—" },
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

  async function loadAllTrackAssignments() {
    await Promise.all(store.tracks.map(function (t) {
      return loadTrackAssignments(t.id);
    }));
  }

  async function reloadCore() {
    var meRes = await api.get("/auth/me");
    store.me = meRes.profile || meRes;

    var results = await Promise.all([
      api.get("/hr/users?role=employee"),
      api.get("/hr/users?role=teacher"),
      api.get("/hr/users?role=curator"),
      api.get("/hr/users?role=hr"),
      api.get("/hr/teachers"),
      api.get("/hr/reports/attendance/users"),
      api.get("/hr/notifications"),
      api.get("/hr/reports/summary"),
      api.get("/hr/strikes"),
      api.get("/hr/appeals"),
      api.get("/hr/lessons"),
      api.get("/hr/tracks"),
      api.get("/hr/conveyor-slots?active_only=true"),
      api.get("/hr/smu-patterns"),
      api.get("/hr/smu-assignments"),
      api.get("/hr/smu-extra-shifts"),
      api.get("/hr/instructors/track-links"),
    ]);

    var employees = (results[0].items || []).map(mapUser);
    var teachers = (results[1].items || []).map(mapUser);
    var curators = (results[2].items || []).map(mapUser);
    var hrs = (results[3].items || []).map(mapUser);
    store.users = employees.concat(teachers, curators, hrs);
    if (store.me && !store.users.some(function (u) { return u.id === store.me.id; })) {
      store.users.push(mapUser(store.me));
    }

    store.teachersMeta = results[4].items || [];

    var attRows = results[5].items || [];
    store.attendanceByUser = {};
    attRows.forEach(function (row) {
      var uid = row.user_id;
      if (!store.attendanceByUser[uid]) store.attendanceByUser[uid] = [];
      store.attendanceByUser[uid].push(row);
    });

    store.notifications = (results[6].items || []).map(function (n, i) {
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

    store.summaryReport = results[7] || null;
    store.strikes = (results[8].items || []).map(mapStrike);
    store.appeals = (results[9].items || []).map(mapStrike);
    store.lessons = (results[10].items || []).map(mapLesson);
    store.tracks = (results[11].items || []).map(mapTrack);
    store.conveyorSlots = (results[12].items || []).map(mapConveyorSlot);
    store.smuPatterns = (results[13].items || []).map(mapSmuPattern);
    store.smuAssignments = results[14].items || [];
    store.smuExtraShifts = results[15].items || [];
    store.trackTeacherLinks = results[16].items || [];
    store.trackAssignments = {};
    store.instructorTracks = {};

    await loadAllTrackAssignments();

    var studentIds = employees.map(function (u) { return u.id; });
    await loadAttendanceIssues(studentIds.slice(0, 50));
  }

  function buildAppData() {
    var hrProfile = store.me ? mapUser(store.me) : null;
    return {
      roles: UI_ROLES,
      users: store.users,
      lessons: store.lessons,
      tracks: function () { return store.tracks; },
      conveyorSlots: function () { return store.conveyorSlots; },
      smuPatterns: function () { return store.smuPatterns; },
      smuAssignments: function () { return store.smuAssignments; },
      smuExtraShifts: function () { return store.smuExtraShifts; },
      smuOverrides: function () { return store.smuOverrides; },
      smuOverrideAt: function (patternId, shiftDate, shiftNumber) {
        return store.smuOverrides[smuOverrideStoreKey(patternId, shiftDate, shiftNumber)] || null;
      },
      trackAssignments: function (trackId) { return store.trackAssignments[trackId] || []; },
      loadTrackAssignments: loadTrackAssignments,
      trackTeacherLinks: function () { return store.trackTeacherLinks; },
      instructorTracks: function (teacherId) { return store.instructorTracks[teacherId] || []; },
      loadInstructorTracks: loadInstructorTracks,
      instructorsForTrack: instructorsForTrack,
      marks: [],
      strikes: store.strikes,
      appeals: store.appeals,
      notifications: store.notifications,
      summaryReport: store.summaryReport,
      session: { hrId: hrProfile ? hrProfile.id : null },
      fullName: fullName,
      userById: userById,
      usersByRole: usersByRole,
      studentTracks: studentTracks,
      studentPrimaryTrack: studentPrimaryTrack,
      teacherTracksFromMeta: teacherTracksFromMeta,
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
        track: row.track ? String(row.track).trim() : null,
      };
    }).filter(function (r) { return r.last_name && r.first_name; });
    if (!items.length) {
      throw new Error("Укажите хотя бы одного пользователя с фамилией и именем");
    }
    return api.post("/hr/users/bulk", { items: items });
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

  async function listStaffRemarks(userId) {
    var res = await api.get("/hr/users/" + userId + "/remarks");
    return (res.items || []).map(function (row) {
      return {
        id: row.id,
        user_id: row.user_id,
        text: row.text,
        issued_by: row.issued_by,
        created_at: row.created_at,
        issuer_name: [row.issuer_last_name, row.issuer_first_name].filter(Boolean).join(" "),
      };
    });
  }

  async function addStaffRemark(userId, text) {
    return api.post("/hr/users/" + userId + "/remarks", { text: text });
  }

  async function patchUserStatus(userId, status, banReason) {
    var body = { status: status };
    if (status === "inactive" && banReason) body.ban_reason = banReason;
    return api.patch("/hr/users/" + userId, body);
  }

  async function listLessons(trackId) {
    var q = trackId ? "?track_id=" + encodeURIComponent(trackId) : "";
    var res = await api.get("/hr/lessons" + q);
    return (res.items || []).map(mapLesson);
  }

  async function createLesson(data) {
    return api.post("/hr/lessons", data);
  }

  async function updateLesson(lessonId, data) {
    var res = await api.patch("/hr/lessons/" + lessonId, data);
    if (res.item) {
      var mapped = mapLesson(res.item);
      store.lessons = store.lessons.map(function (l) {
        return String(l.id) === String(lessonId) ? mapped : l;
      });
    }
    return res;
  }

  async function deleteLesson(lessonId) {
    var res = await api.del("/hr/lessons/" + lessonId);
    store.lessons = store.lessons.filter(function (l) { return String(l.id) !== String(lessonId); });
    return res;
  }

  async function loadTrackAssignments(trackId) {
    var res = await api.get("/hr/tracks/" + trackId + "/assignments");
    store.trackAssignments[trackId] = res.items || [];
    return store.trackAssignments[trackId];
  }

  async function createTrack(data) {
    var res = await api.post("/hr/tracks", data);
    await reloadCore();
    return res;
  }

  async function updateTrack(trackId, data) {
    return api.patch("/hr/tracks/" + trackId, data);
  }

  async function deleteTrack(trackId) {
    var res = await api.del("/hr/tracks/" + trackId);
    var idx = store.tracks.findIndex(function (t) { return String(t.id) === String(trackId); });
    if (idx >= 0) store.tracks.splice(idx, 1);
    return res;
  }

  async function assignUserTrack(userId, trackId, status, dueDate) {
    var body = { track_id: trackId, status: status || "active" };
    if (dueDate) body.due_date = dueDate;
    return api.post("/hr/users/" + userId + "/tracks", body);
  }

  async function previewFormation(data) {
    return api.post("/hr/formation/preview", data);
  }

  async function runAutoFormation(data) {
    return api.post("/hr/formation/auto-run", data || {});
  }

  async function loadFormationPlan(data) {
    return api.post("/hr/formation/plan", data);
  }

  async function loadFormationPlanMonth(data) {
    return api.post("/hr/formation/plan/month", data);
  }

  async function createFormationPlan(data) {
    return api.post("/hr/formation/plan/create", data);
  }

  async function createFormationPlanMonth(data) {
    return api.post("/hr/formation/plan/month/create", data);
  }

  async function loadFormationLog(params) {
    var q = new URLSearchParams();
    if (params && params.from_date) q.set("from_date", params.from_date);
    if (params && params.to_date) q.set("to_date", params.to_date);
    if (params && params.limit) q.set("limit", String(params.limit));
    var suffix = q.toString() ? "?" + q.toString() : "";
    var res = await api.get("/hr/formation/log" + suffix);
    return res.items || [];
  }

  async function loadTrackFormationSettings(trackId) {
    return api.get("/hr/tracks/" + trackId + "/formation-settings");
  }

  async function updateTrackFormationSettings(trackId, data) {
    return api.patch("/hr/tracks/" + trackId + "/formation-settings", data);
  }

  async function recalculateTrackWeights(trackId, force) {
    var q = force ? "?force=true" : "";
    return api.post("/hr/tracks/" + trackId + "/recalculate-weights" + q);
  }

  async function createSmuPattern(data) {
    return api.post("/hr/smu-patterns", data);
  }

  async function updateSmuPattern(patternId, data) {
    return api.patch("/hr/smu-patterns/" + patternId, data);
  }

  async function deleteSmuPattern(patternId) {
    var res = await api.del("/hr/smu-patterns/" + patternId);
    var idx = store.smuPatterns.findIndex(function (p) { return String(p.id) === String(patternId); });
    if (idx >= 0) store.smuPatterns.splice(idx, 1);
    clearSmuOverrideIndexForPattern(patternId);
    return res;
  }

  async function assignUserSmu(userId, smuPatternId, shiftNumber) {
    var body = { smu_pattern_id: smuPatternId, shift_number: shiftNumber || 1 };
    return api.post("/hr/users/" + userId + "/smu", body);
  }

  function smuOverrideStoreKey(patternId, shiftDate, shiftNumber) {
    return String(patternId) + ":" + String(shiftDate).slice(0, 10) + ":" + String(shiftNumber);
  }

  function indexSmuOverrides(items) {
    (items || []).forEach(function (row) {
      var key = smuOverrideStoreKey(row.smu_pattern_id, row.shift_date, row.shift_number);
      store.smuOverrides[key] = row;
    });
  }

  function clearSmuOverrideIndexForPattern(patternId, fromDate, toDate) {
    var prefix = String(patternId) + ":";
    Object.keys(store.smuOverrides).forEach(function (key) {
      if (key.indexOf(prefix) !== 0) return;
      var datePart = key.slice(prefix.length, prefix.length + 10);
      if (fromDate && datePart < fromDate) return;
      if (toDate && datePart > toDate) return;
      delete store.smuOverrides[key];
    });
  }

  async function loadSmuPatternOverrides(patternId, fromDate, toDate) {
    var q = [];
    if (fromDate) q.push("from_date=" + encodeURIComponent(fromDate));
    if (toDate) q.push("to_date=" + encodeURIComponent(toDate));
    var suffix = q.length ? "?" + q.join("&") : "";
    var res = await api.get("/hr/smu-patterns/" + patternId + "/overrides" + suffix);
    clearSmuOverrideIndexForPattern(patternId, fromDate, toDate);
    indexSmuOverrides(res.items || []);
    return res.items || [];
  }

  async function setSmuPatternOverride(patternId, shiftDate, shiftNumber, state, note) {
    var res = await api.put("/hr/smu-patterns/" + patternId + "/overrides", {
      shift_date: shiftDate,
      shift_number: shiftNumber,
      state: state || "auto",
      note: note || null,
    });
    var key = smuOverrideStoreKey(patternId, shiftDate, shiftNumber);
    if (res.cleared || !res.item) delete store.smuOverrides[key];
    else store.smuOverrides[key] = res.item;
    return res;
  }

  async function clearSmuPatternOverrides(patternId, fromDate, toDate) {
    var q = [];
    if (fromDate) q.push("from_date=" + encodeURIComponent(fromDate));
    if (toDate) q.push("to_date=" + encodeURIComponent(toDate));
    var suffix = q.length ? "?" + q.join("&") : "";
    var res = await api.del("/hr/smu-patterns/" + patternId + "/overrides" + suffix);
    clearSmuOverrideIndexForPattern(patternId, fromDate, toDate);
    return res;
  }

  async function applySmuPatternPreset(patternId, preset, anchorDate, clearOverrides) {
    var res = await api.post("/hr/smu-patterns/" + patternId + "/apply-preset", {
      preset: preset,
      anchor_date: anchorDate || null,
      clear_overrides: clearOverrides !== false,
    });
    if (res.item) {
      var idx = store.smuPatterns.findIndex(function (p) { return p.id === patternId; });
      if (idx >= 0) store.smuPatterns[idx] = mapSmuPattern(res.item);
      else store.smuPatterns.push(mapSmuPattern(res.item));
    }
    if (clearOverrides !== false) {
      store.smuOverrides = {};
    }
    return res;
  }

  async function removeUserSmu(userId) {
    return api.del("/hr/users/" + userId + "/smu");
  }

  async function addSmuExtraShift(userId, shiftDate, shiftNumber, note) {
    return api.post("/hr/smu-extra-shifts", {
      user_id: userId,
      shift_date: shiftDate,
      shift_number: shiftNumber || 1,
      note: note || null,
    });
  }

  async function updateSmuExtraShift(shiftId, data) {
    return api.patch("/hr/smu-extra-shifts/" + shiftId, data || {});
  }

  async function removeSmuExtraShift(shiftId) {
    return api.del("/hr/smu-extra-shifts/" + shiftId);
  }

  async function syncCuratorWards(curatorId, userIds) {
    return api.post("/hr/curators/" + curatorId + "/wards/sync", { user_ids: userIds || [] });
  }

  async function loadInstructorTracks(teacherId) {
    var res = await api.get("/hr/instructors/" + teacherId + "/tracks");
    store.instructorTracks[teacherId] = res.items || [];
    return store.instructorTracks[teacherId];
  }

  async function syncInstructorTracks(teacherId, trackIds) {
    var res = await api.post("/hr/instructors/" + teacherId + "/tracks/sync", { track_ids: trackIds || [] });
    store.instructorTracks[teacherId] = null;
    var linksRes = await api.get("/hr/instructors/track-links");
    store.trackTeacherLinks = linksRes.items || [];
    return res;
  }

  function instructorsForTrack(trackId) {
    if (!trackId) return store.users.filter(function (u) { return u.id_role === "teacher"; });
    var ids = store.trackTeacherLinks
      .filter(function (l) { return l.track_id === trackId; })
      .map(function (l) { return l.teacher_id; });
    if (!ids.length) return store.users.filter(function (u) { return u.id_role === "teacher"; });
    return store.users.filter(function (u) { return ids.indexOf(u.id) >= 0; });
  }

  function instructorsOnTrack(trackId) {
    return store.trackTeacherLinks.filter(function (l) { return l.track_id === trackId; });
  }

  function instructorTrackIds(teacherId) {
    return store.trackTeacherLinks
      .filter(function (l) { return l.teacher_id === teacherId; })
      .map(function (l) { return l.track_id; });
  }

  async function addInstructorToTrack(teacherId, trackId) {
    var ids = instructorTrackIds(teacherId).slice();
    if (ids.indexOf(trackId) < 0) ids.push(trackId);
    return syncInstructorTracks(teacherId, ids);
  }

  async function removeInstructorFromTrack(teacherId, trackId) {
    var ids = instructorTrackIds(teacherId).filter(function (id) { return id !== trackId; });
    return syncInstructorTracks(teacherId, ids);
  }

  function getConveyorSlots() {
    return store.conveyorSlots.slice();
  }

  async function runLessonReminders() {
    var response = await fetch("/api/v1/db/lesson-reminders/run", { method: "POST" });
    var payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }
    if (!response.ok) {
      throw new Error((payload && payload.detail) || response.statusText || "Ошибка запуска напоминаний");
    }
    return payload;
  }

  global.HrApi = {
    bootstrap: bootstrap,
    refresh: refresh,
    updateUser: updateUser,
    updateStudent: updateStudent,
    createUsersBulk: createUsersBulk,
    addStrike: addStrike,
    revokeStrike: revokeStrike,
    resolveAppeal: resolveAppeal,
    listStaffRemarks: listStaffRemarks,
    addStaffRemark: addStaffRemark,
    patchUserStatus: patchUserStatus,
    listLessons: listLessons,
    createLesson: createLesson,
    updateLesson: updateLesson,
    deleteLesson: deleteLesson,
    createTrack: createTrack,
    updateTrack: updateTrack,
    deleteTrack: deleteTrack,
    assignUserTrack: assignUserTrack,
    previewFormation: previewFormation,
    runAutoFormation: runAutoFormation,
    loadFormationPlan: loadFormationPlan,
    loadFormationPlanMonth: loadFormationPlanMonth,
    createFormationPlan: createFormationPlan,
    createFormationPlanMonth: createFormationPlanMonth,
    loadFormationLog: loadFormationLog,
    loadTrackFormationSettings: loadTrackFormationSettings,
    updateTrackFormationSettings: updateTrackFormationSettings,
    loadTrackAssignments: loadTrackAssignments,
    recalculateTrackWeights: recalculateTrackWeights,
    createSmuPattern: createSmuPattern,
    updateSmuPattern: updateSmuPattern,
    deleteSmuPattern: deleteSmuPattern,
    loadSmuPatternOverrides: loadSmuPatternOverrides,
    setSmuPatternOverride: setSmuPatternOverride,
    clearSmuPatternOverrides: clearSmuPatternOverrides,
    applySmuPatternPreset: applySmuPatternPreset,
    assignUserSmu: assignUserSmu,
    removeUserSmu: removeUserSmu,
    addSmuExtraShift: addSmuExtraShift,
    updateSmuExtraShift: updateSmuExtraShift,
    removeSmuExtraShift: removeSmuExtraShift,
    syncCuratorWards: syncCuratorWards,
    loadInstructorTracks: loadInstructorTracks,
    syncInstructorTracks: syncInstructorTracks,
    instructorsForTrack: instructorsForTrack,
    instructorsOnTrack: instructorsOnTrack,
    addInstructorToTrack: addInstructorToTrack,
    removeInstructorFromTrack: removeInstructorFromTrack,
    parseFio: parseFio,
    apiRoleCode: apiRoleCode,
    getConveyorSlots: getConveyorSlots,
    runLessonReminders: runLessonReminders,
  };
})(window);
