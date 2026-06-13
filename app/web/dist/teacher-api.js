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
    teacherId: null,
    users: [],
    groups: [],
    parentGroups: [],
    groupMembers: [],
    myLessons: [],
    allLessons: [],
    marks: [],
    markHistory: [],
    reportGroups: [],
    reportUsers: [],
    attendanceCache: {},
  };

  function uiRoleCode(apiCode) {
    return ROLE_API_TO_UI[apiCode] || apiCode;
  }

  function formatTime(d) {
    return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  }

  function mapUser(row) {
    return {
      id: row.id,
      firstName: row.first_name,
      lastName: row.last_name,
      middleName: row.middle_name || null,
      id_max: row.max_id != null ? String(row.max_id) : null,
      phone: row.phone || null,
      id_role: uiRoleCode(row.role_code),
      status: row.status === "inactive" ? "inactive" : "active",
      id_curator: row.id_curator || null,
      strikes: row.strike_count || 0,
    };
  }

  function mapGroup(row) {
    return {
      id: row.id,
      id_parent: row.id_parent || null,
      name: row.name,
      parent_name: row.parent_name || null,
      status: row.status || "active",
      members: row.members || [],
    };
  }

  function mapLesson(row) {
    var d = row.starts_at ? new Date(row.starts_at) : null;
    var de = row.ends_at ? new Date(row.ends_at) : null;
    return {
      id: row.id,
      id_group: row.group_id,
      id_teacher: row.teacher_id,
      date: d ? d.toISOString().slice(0, 10) : "",
      time: d ? formatTime(d) : "",
      timeEnd: de ? formatTime(de) : "",
      place: row.place || "",
      type: row.lesson_type,
      title: row.lesson_title || row.title || (row.lesson_type === "practice" ? "Практика" : "Лекция"),
      startsAt: row.starts_at,
      endsAt: row.ends_at,
      studentIds: row.member_ids && row.member_ids.length ? row.member_ids : null,
      teacher_name: row.teacher_name || [row.teacher_last_name, row.teacher_first_name].filter(Boolean).join(" "),
    };
  }

  function mapMark(row, lessonId, userId) {
    return {
      id: row.mark_id || (lessonId + ":" + userId),
      id_lesson: lessonId,
      id_user: userId,
      mark: row.attendance_status || row.status,
    };
  }

  function mapHistory(row) {
    return {
      id: row.id,
      id_mark: row.mark_id,
      id_lesson: row.lesson_id,
      id_user: row.user_id,
      old_mark: row.old_status,
      mark: row.new_status,
      changed_by: row.changed_by,
      changed_by_name: [row.changed_by_first_name, row.changed_by_last_name].filter(Boolean).join(" "),
      changed_at: row.changed_at,
      user_name: [row.first_name, row.last_name].filter(Boolean).join(" "),
      group_name: row.group_name,
      starts_at: row.starts_at,
    };
  }

  function fullName(u) {
    if (!u) return "—";
    return [u.firstName, u.lastName].filter(Boolean).join(" ");
  }

  function userById(id) {
    return store.users.find(function (u) { return u.id === id; });
  }

  function rebuildGroupMembers(groups) {
    var members = [];
    groups.forEach(function (g) {
      (g.members || []).forEach(function (m) {
        members.push({
          id_group: g.id,
          id_user: m.id,
          type: uiRoleCode(m.role_code) === "teacher" ? "teacher" : "student",
        });
      });
    });
    return members;
  }

  function collectUsers(groups, meProfile) {
    var map = {};
    groups.forEach(function (g) {
      (g.members || []).forEach(function (m) {
        if (!map[m.id]) map[m.id] = mapUser(m);
      });
    });
    if (meProfile && !map[meProfile.id]) map[meProfile.id] = mapUser(meProfile);
    return Object.keys(map).map(function (k) { return map[k]; });
  }

  function courses() {
    return store.parentGroups.length
      ? store.parentGroups
      : store.groups.filter(function (g) { return !g.id_parent; });
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

  function courseOfGroup(groupId) {
    var g = store.groups.find(function (x) { return x.id === groupId; });
    if (!g) return null;
    if (!g.id_parent) return g;
    var parent = store.parentGroups.find(function (x) { return x.id === g.id_parent; })
      || store.groups.find(function (x) { return x.id === g.id_parent; });
    if (parent) return parent;
    if (g.parent_name) {
      return { id: g.id_parent, id_parent: null, name: g.parent_name, status: "active" };
    }
    return null;
  }

  async function loadParentGroups(groups) {
    store.parentGroups = groups
      .filter(function (g) { return g.id_parent; })
      .map(function (g) {
        return {
          id: g.id_parent,
          id_parent: null,
          name: g.parent_name || "Направление",
          status: "active",
          members: [],
        };
      })
      .filter(function (p, i, arr) {
        return arr.findIndex(function (x) { return x.id === p.id; }) === i;
      });
  }

  async function loadMyLessons() {
    var res = await api.get("/teacher/lessons");
    store.myLessons = (res.items || []).map(mapLesson);
    store.allLessons = store.myLessons.slice();
    await rebuildMarksFromLessons(store.myLessons);
  }

  async function rebuildMarksFromLessons(lessons) {
    var marks = [];
    await Promise.all(lessons.filter(function (l) {
      return l.id_teacher === store.teacherId;
    }).map(async function (l) {
      try {
        var res = await api.get("/teacher/lessons/" + l.id + "/attendance");
        (res.items || []).forEach(function (row) {
          if (row.attendance_status) {
            marks.push(mapMark(row, l.id, row.user_id));
          }
        });
      } catch (_e) { /* ignore */ }
    }));
    store.marks = marks;
  }

  async function loadCalendarLessons(fromDate, toDate) {
    var q = "?all_teachers=true";
    if (fromDate) q += "&from_date=" + encodeURIComponent(fromDate.toISOString());
    if (toDate) {
      var end = new Date(toDate);
      end.setHours(23, 59, 59, 999);
      q += "&to_date=" + encodeURIComponent(end.toISOString());
    }
    var res = await api.get("/teacher/lessons" + q);
    store.allLessons = (res.items || []).map(mapLesson);
    return store.allLessons;
  }

  async function loadReports(groupId) {
    var gq = groupId ? "?group_id=" + encodeURIComponent(groupId) : "";
    var results = await Promise.all([
      api.get("/teacher/reports/attendance/groups" + gq),
      api.get("/teacher/reports/attendance/users" + gq),
    ]);
    store.reportGroups = results[0].items || [];
    store.reportUsers = results[1].items || [];
    return { groups: store.reportGroups, users: store.reportUsers };
  }

  async function loadMarkHistory(lessonId) {
    var q = lessonId ? "?lesson_id=" + encodeURIComponent(lessonId) : "";
    var res = await api.get("/teacher/attendance/history" + q);
    store.markHistory = (res.items || []).map(mapHistory);
    return store.markHistory;
  }

  async function reloadCore() {
    var meRes = await api.get("/teacher/me");
    store.me = meRes.profile || meRes;
    store.teacherId = store.me ? store.me.id : null;

    var groupsRes = await api.get("/teacher/groups");
    store.groups = (groupsRes.items || []).map(mapGroup);
    store.groupMembers = rebuildGroupMembers(store.groups);
    store.users = collectUsers(store.groups, store.me);
    await loadParentGroups(store.groups);

    await loadMyLessons();
    await loadReports(null);
    await loadMarkHistory(null);
  }

  function buildAppData() {
    var teacherProfile = store.me ? mapUser(store.me) : null;
    return {
      roles: UI_ROLES,
      users: store.users,
      groups: store.groups.concat(store.parentGroups.filter(function (p) {
        return !store.groups.some(function (g) { return g.id === p.id; });
      })),
      groupMembers: store.groupMembers,
      lessons: store.allLessons,
      myLessons: store.myLessons,
      marks: store.marks,
      markHistory: store.markHistory,
      reportGroups: store.reportGroups,
      reportUsers: store.reportUsers,
      session: { teacherId: store.teacherId },
      fullName: fullName,
      userById: userById,
      courses: courses,
      workingGroups: workingGroups,
      allWorkingGroups: allWorkingGroups,
      groupStudents: groupStudents,
      courseOfGroup: courseOfGroup,
      roleById: function (id) { return UI_ROLES.find(function (r) { return r.id === id; }); },
      roleCode: function (id) { return UI_ROLES.find(function (r) { return r.id === id; })?.code || ""; },
      statusLabel: { active: "активен", inactive: "не активен" },
      markLabel: { present: "был", absent: "не был", late: "опоздал" },
      lessonTypeLabel: { lecture: "лекция", practice: "практика" },
    };
  }

  async function bootstrap() {
    await reloadCore();
    return buildAppData();
  }

  async function refresh() {
    await reloadCore();
    return buildAppData();
  }

  async function loadLessonAttendance(lessonId) {
    var res = await api.get("/teacher/lessons/" + lessonId + "/attendance");
    store.attendanceCache[lessonId] = res.items || [];
    return store.attendanceCache[lessonId];
  }

  async function saveAttendance(lessonId, marksMap) {
    var marks = Object.keys(marksMap).map(function (uid) {
      return { user_id: uid, status: marksMap[uid] };
    });
    var res = await api.post("/teacher/lessons/" + lessonId + "/attendance", { marks: marks });
    store.attendanceCache[lessonId] = res.items || [];
    await rebuildMarksFromLessons(store.myLessons);
    await loadMarkHistory(null);
    return res.items;
  }

  async function createLesson(data) {
    var body = {
      group_id: data.group_id,
      starts_at: data.starts_at,
      ends_at: data.ends_at,
      place: data.place,
      lesson_type: data.lesson_type,
      title: data.title || null,
      member_ids: data.member_ids || null,
    };
    var lesson = await api.post("/teacher/lessons", body);
    await reloadCore();
    return mapLesson(lesson);
  }

  async function updateLesson(lessonId, data) {
    var body = {};
    if (data.starts_at != null) body.starts_at = data.starts_at;
    if (data.ends_at != null) body.ends_at = data.ends_at;
    if (data.place != null) body.place = data.place;
    if (data.lesson_type != null) body.lesson_type = data.lesson_type;
    if (data.title != null) body.title = data.title;
    var lesson = await api.patch("/teacher/lessons/" + lessonId, body);
    await reloadCore();
    return mapLesson(lesson);
  }

  async function deleteLesson(lessonId) {
    await api.del("/teacher/lessons/" + lessonId);
    await reloadCore();
  }

  global.TeacherApi = {
    bootstrap: bootstrap,
    refresh: refresh,
    loadCalendarLessons: loadCalendarLessons,
    loadReports: loadReports,
    loadMarkHistory: loadMarkHistory,
    loadLessonAttendance: loadLessonAttendance,
    saveAttendance: saveAttendance,
    createLesson: createLesson,
    updateLesson: updateLesson,
    deleteLesson: deleteLesson,
  };
})(window);
