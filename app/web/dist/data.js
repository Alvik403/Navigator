/* eslint-disable no-unused-vars */
/**
 * Единая демо-модель MAX RASS.
 * Пользователь: id, ФИО, id_max, телефон, id_роли, статус, id_куратора, страйки
 * Группа: id, id_parent, name, id_hr, createdAt, status (без parent = направление/курс)
 * Участник группы: id_group + id_user + type (student | teacher)
 * Занятие: id, id_group, id_teacher, date, time, place, type (lecture | practice)
 * Отметка: present | absent | late + история изменений
 */
window.APP_DATA = (function () {
  "use strict";

  const ROLES = [
    { id: 1, code: "admin", name: "Администратор" },
    { id: 2, code: "hr", name: "HR" },
    { id: 3, code: "teacher", name: "Преподаватель" },
    { id: 4, code: "student", name: "Ученик" },
    { id: 5, code: "curator", name: "Куратор" }
  ];

  const FIRST = ["Иван","Алексей","Дмитрий","Сергей","Андрей","Михаил","Никита","Павел","Артём","Максим","Егор","Роман","Владимир","Кирилл","Олег","Анна","Мария","Елена","Ольга","Наталья","Татьяна","Ирина","Светлана","Екатерина","Виктория","Полина","Алина","Дарья","Юлия","Ксения"];
  const LAST = ["Иванов","Петров","Сидоров","Смирнов","Кузнецов","Попов","Васильев","Соколов","Михайлов","Новиков","Фёдоров","Морозов","Волков","Алексеев","Лебедев","Семёнов","Егоров","Павлов","Козлов","Степанов","Николаев","Орлов","Андреев","Макаров","Никитин","Захаров","Зайцев","Соловьёв","Борисов","Яковлев"];
  const BUILDINGS = ["Корпус А","Корпус Б","Корпус В","Учебный центр"];
  const ROOMS = ["101","212","304","305","401","115"];
  const TOPICS = ["REST API","SQL и индексы","React hooks","Docker","CI/CD","UX research","Тестирование","Scrum практики"];

  function seededRandom(seed) {
    let s = seed;
    return function () { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
  }
  function pick(rng, arr) { return arr[Math.floor(rng() * arr.length)]; }
  function phone(rng) { return "+7" + (900 + Math.floor(rng() * 99)) + String(Math.floor(rng() * 10000000)).padStart(7, "0"); }
  function maxId(rng, n) { return String(100000000 + n + Math.floor(rng() * 900000000)); }
  function dateStr(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function roleById(id) { return ROLES.find(r => r.id === id); }
  function roleCode(id) { return roleById(id)?.code || ""; }

  function build() {
    const rng = seededRandom(42);
    const users = [];
    let uid = 1, maxSeq = 1;

    function addUser(firstName, lastName, roleId, opts) {
      const o = opts || {};
      const u = {
        id: uid++,
        firstName, lastName,
        id_max: o.id_max != null ? o.id_max : maxId(rng, maxSeq++),
        phone: o.phone != null ? o.phone : phone(rng),
        id_role: roleId,
        status: o.status || "active",
        id_curator: o.id_curator || null,
        strikes: o.strikes || 0
      };
      users.push(u);
      return u;
    }

    addUser("Системный", "Админ", 1);
    const hrs = [];
    for (let i = 0; i < 4; i++) hrs.push(addUser(pick(rng, FIRST), pick(rng, LAST), 2));

    const teachers = [];
    for (let i = 0; i < 12; i++) teachers.push(addUser(pick(rng, FIRST), pick(rng, LAST), 3));

    const curators = [];
    for (let i = 0; i < 6; i++) {
      curators.push(addUser(pick(rng, FIRST), pick(rng, LAST), 5, {
        id_max: maxId(rng, maxSeq++),
        phone: phone(rng)
      }));
    }

    const students = [];
    while (students.length < 120) {
      const fn = pick(rng, FIRST), ln = pick(rng, LAST);
      const needsCurator = rng() < 0.22;
      students.push(addUser(fn, ln, 4, {
        id_max: needsCurator ? null : maxId(rng, maxSeq++),
        phone: needsCurator ? null : phone(rng),
        id_curator: null,
        strikes: rng() > 0.95 ? Math.floor(rng() * 3) + 1 : 0,
        status: rng() > 0.1 ? "active" : "inactive"
      }));
    }

    students.filter(s => !s.phone && !s.id_max).forEach((s, i) => {
      s.id_curator = curators[i % curators.length].id;
    });

    const courseNames = ["Frontend", "Backend", "Data Analytics", "UX/UI Design", "DevOps", "Mobile", "QA", "Project Management"];
    const groups = [];
    let gid = 1;
    const courses = courseNames.map((name, i) => {
      const g = {
        id: gid++,
        id_parent: null,
        name,
        id_hr: hrs[i % hrs.length].id,
        createdAt: "2024-09-" + String(10 + i).padStart(2, "0"),
        status: "active"
      };
      groups.push(g);
      return g;
    });

    const workGroupNames = [
      ["Frontend-24","Frontend-25"], ["Backend-22","Backend-24"], ["DA-11","DA-12"],
      ["Design-08","Design-09"], ["DevOps-03","DevOps-04"], ["Mobile-07","Mobile-09"],
      ["QA-05","QA-06"], ["PM-02","PM-03"]
    ];
    const workingGroups = [];
    courses.forEach((course, ci) => {
      workGroupNames[ci].forEach((name, wi) => {
        const g = {
          id: gid++,
          id_parent: course.id,
          name,
          id_hr: course.id_hr,
          createdAt: "2025-01-" + String(5 + wi + ci).padStart(2, "0"),
          status: wi % 4 === 0 ? "forming" : "active"
        };
        groups.push(g);
        workingGroups.push(g);
      });
    });

    const groupMembers = [];
    function addMember(groupId, userId, type) {
      groupMembers.push({ id_group: groupId, id_user: userId, type });
    }

    courses.forEach((course, ci) => {
      const t1 = teachers[ci % teachers.length];
      const t2 = teachers[(ci + 3) % teachers.length];
      addMember(course.id, t1.id, "teacher");
      if (ci % 2 === 0) addMember(course.id, t2.id, "teacher");
    });

    const LOGGED_HR_ID = hrs[0].id;
    const LOGGED_TEACHER_ID = teachers[2].id;
    const LOGGED_ADMIN_ID = users[0].id;

    workingGroups.forEach((wg, gi) => {
      const teacher = teachers[gi % teachers.length];
      addMember(wg.id, teacher.id, "teacher");
      const count = 8 + (gi % 5);
      for (let m = 0; m < count; m++) {
        const st = students[(gi * 7 + m) % students.length];
        if (!groupMembers.some(x => x.id_group === wg.id && x.id_user === st.id)) {
          addMember(wg.id, st.id, "student");
        }
      }
    });

    ["Backend-24", "Frontend-25", "DA-11"].forEach(name => {
      const wg = workingGroups.find(g => g.name === name);
      if (!wg) return;
      const idx = groupMembers.findIndex(m => m.id_group === wg.id && m.type === "teacher");
      if (idx >= 0) groupMembers[idx].id_user = LOGGED_TEACHER_ID;
      else addMember(wg.id, LOGGED_TEACHER_ID, "teacher");
    });

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const lessons = [];
    let lid = 1;

    const ALL_SLOTS = [
      { time: "09:00", timeEnd: "10:00", h: 9, m: 0, dur: 60 },
      { time: "10:30", timeEnd: "11:30", h: 10, m: 30, dur: 60 },
      { time: "12:00", timeEnd: "13:00", h: 12, m: 0, dur: 60 },
      { time: "13:30", timeEnd: "14:30", h: 13, m: 30, dur: 60 },
      { time: "15:00", timeEnd: "16:00", h: 15, m: 0, dur: 60 },
      { time: "16:30", timeEnd: "17:30", h: 16, m: 30, dur: 60 },
      { time: "18:00", timeEnd: "19:00", h: 18, m: 0, dur: 60 }
    ];
    const DAY_OFFSETS = [-12, -9, -7, -5, -3, -1, 0, 2, 4, 6, 8, 11, 14, 17, 20];
    const allPlaces = BUILDINGS.flatMap(b => ROOMS.map(r => b + ", каб. " + r));

    function lessonStatusFor(starts, ends) {
      const now = new Date();
      if (ends < now) return "done";
      if (starts <= now && ends >= now) return "now";
      if (starts.toDateString() === now.toDateString()) return "soon";
      return "planned";
    }

    function slotTimes(d, slot) {
      const starts = new Date(d);
      starts.setHours(slot.h, slot.m, 0, 0);
      const ends = new Date(starts);
      ends.setMinutes(ends.getMinutes() + slot.dur);
      return { starts, ends };
    }

    function lessonStudentIds(lesson) {
      if (lesson.studentIds?.length) return lesson.studentIds;
      return groupMembers
        .filter(m => m.id_group === lesson.id_group && m.type === "student")
        .map(m => m.id_user);
    }

    function hasConflict(date, starts, ends, tid, gid, place, studentIds) {
      return lessons.some(l => {
        if (l.date !== date) return false;
        const ls = new Date(l.startsAt);
        const le = new Date(l.endsAt);
        if (!(starts < le && ls < ends)) return false;
        if (l.id_teacher === tid) return true;
        if (l.id_group === gid) return true;
        if (l.place === place) return true;
        if (studentIds?.length) {
          const theirs = lessonStudentIds(l);
          if (studentIds.some(sid => theirs.includes(sid))) return true;
        }
        return false;
      });
    }

    workingGroups.forEach((wg, gi) => {
      const tid = groupMembers.find(m => m.id_group === wg.id && m.type === "teacher")?.id_user;
      if (!tid) return;
      const isLoggedGroup = tid === LOGGED_TEACHER_ID;
      const numLessons = isLoggedGroup ? 6 + (gi % 2) : 3 + (gi % 3);

      for (let li = 0; li < numLessons; li++) {
        const seed = gi * 19 + li * 37;
        let placed = false;
        for (let attempt = 0; attempt < 50 && !placed; attempt++) {
          const dayOffset = DAY_OFFSETS[(seed + attempt * 5) % DAY_OFFSETS.length];
          const slot = ALL_SLOTS[(seed + attempt * 3) % ALL_SLOTS.length];
          const d = new Date(today);
          d.setDate(d.getDate() + dayOffset);
          const ds = dateStr(d);
          const { starts, ends } = slotTimes(d, slot);
          const place = allPlaces[(seed + attempt * 2) % allPlaces.length];
          const isPractice = (gi + li + attempt) % 4 === 0;
          let studentIds = null;
          if (isPractice) {
            const sts = groupMembers
              .filter(m => m.id_group === wg.id && m.type === "student")
              .map(m => m.id_user);
            const half = sts.slice(0, Math.max(2, Math.ceil(sts.length / 2)));
            studentIds = half;
          }
          if (hasConflict(ds, starts, ends, tid, wg.id, place, studentIds)) continue;

          lessons.push({
            id: lid++,
            id_group: wg.id,
            id_teacher: tid,
            date: ds,
            time: slot.time,
            timeEnd: slot.timeEnd,
            place,
            type: isPractice ? "practice" : "lecture",
            title: TOPICS[(gi + li + attempt) % TOPICS.length],
            startsAt: starts.toISOString(),
            endsAt: ends.toISOString(),
            status: lessonStatusFor(starts, ends),
            studentIds
          });
          placed = true;
        }
      }
    });

    const marks = [];
    const markHistory = [];
    let mid = 1, hid = 1;

    lessons.filter(l => l.status === "done").slice(0, 15).forEach(lesson => {
      const studentIds = groupMembers.filter(m => m.id_group === lesson.id_group && m.type === "student").map(m => m.id_user);
      studentIds.forEach((sid, i) => {
        const markVal = i % 7 === 0 ? "absent" : (i % 5 === 0 ? "late" : "present");
        const mark = { id: mid++, id_lesson: lesson.id, id_user: sid, mark: markVal };
        marks.push(mark);
        markHistory.push({
          id: hid++,
          id_mark: mark.id,
          mark: markVal,
          changed_by: lesson.id_teacher,
          changed_at: lesson.endsAt
        });
      });
    });

    const strikes = [];
    let sid = 1;
    students.filter(s => s.strikes > 0).forEach(s => {
      for (let i = 0; i < s.strikes; i++) {
        strikes.push({
          id: sid++,
          id_user: s.id,
          id_lesson: lessons[i % lessons.length]?.id,
          reason: i % 2 === 0 ? "absent" : "late",
          created_at: "2025-05-" + String(10 + i).padStart(2, "0")
        });
      }
      if (s.strikes >= 3) s.status = "inactive";
    });

    const notifications = [];
    let nid = 1;
    function notify(userId, type, text) {
      notifications.push({ id: nid++, id_user: userId, type, text, read: false, created_at: new Date().toISOString() });
    }

    const loggedTeacherLessons = lessons.filter(l => l.id_teacher === LOGGED_TEACHER_ID && l.status !== "done");
    loggedTeacherLessons.slice(0, 2).forEach(l => {
      notify(LOGGED_TEACHER_ID, "lesson_reminder", `Занятие через 24 ч: ${l.title} · ${l.place}`);
    });

    students.slice(0, 5).forEach(s => {
      notify(s.id, "lesson_reminder", "Занятие завтра в 10:30 · Корпус А, каб. 212");
      if (s.strikes) notify(s.id, "strike", `Страйк ${s.strikes}/3 за пропуск занятия`);
    });

    curators.forEach(c => {
      const wards = students.filter(s => s.id_curator === c.id);
      wards.slice(0, 2).forEach(w => {
        notify(c.id, "ward_lesson", `Подопечный ${fullName(w)}: занятие завтра 14:30`);
        if (w.strikes) notify(c.id, "ward_strike", `Подопечный ${fullName(w)}: страйк ${w.strikes}/3`);
      });
    });

    hrs.forEach(h => {
      notify(h.id, "attendance_alert", "Ученик Иванов И. опоздал на занятие Backend-24");
      notify(h.id, "attendance_alert", "Ученик Петров П. не был на занятии DA-11");
    });

    return {
      roles: ROLES,
      users,
      groups,
      groupMembers,
      lessons,
      marks,
      markHistory,
      strikes,
      notifications,
      session: {
        hrId: LOGGED_HR_ID,
        teacherId: LOGGED_TEACHER_ID,
        adminId: LOGGED_ADMIN_ID
      }
    };
  }

  function fullName(u) {
    if (!u) return "—";
    return u.firstName + " " + u.lastName;
  }

  function userById(id) {
    return DATA.users.find(u => u.id === id);
  }

  function usersByRole(code) {
    const role = DATA.roles.find(r => r.code === code);
    return role ? DATA.users.filter(u => u.id_role === role.id) : [];
  }

  function courses() {
    return DATA.groups.filter(g => g.id_parent === null);
  }

  function workingGroups(parentId) {
    return DATA.groups.filter(g => g.id_parent === parentId);
  }

  function allWorkingGroups() {
    return DATA.groups.filter(g => g.id_parent !== null);
  }

  function groupStudents(groupId) {
    return DATA.groupMembers
      .filter(m => m.id_group === groupId && m.type === "student")
      .map(m => userById(m.id_user))
      .filter(Boolean);
  }

  function groupTeachers(groupId) {
    return DATA.groupMembers
      .filter(m => m.id_group === groupId && m.type === "teacher")
      .map(m => userById(m.id_user))
      .filter(Boolean);
  }

  function studentWorkGroup(studentId) {
    const m = DATA.groupMembers.find(x => x.id_user === studentId && x.type === "student");
    return m ? DATA.groups.find(g => g.id === m.id_group) : null;
  }

  function courseOfGroup(groupId) {
    const g = DATA.groups.find(x => x.id === groupId);
    if (!g) return null;
    if (!g.id_parent) return g;
    return DATA.groups.find(x => x.id === g.id_parent);
  }

  const DATA = build();

  return {
    ...DATA,
    fullName,
    userById,
    usersByRole,
    courses,
    workingGroups,
    allWorkingGroups,
    groupStudents,
    groupTeachers,
    studentWorkGroup,
    courseOfGroup,
    roleById,
    roleCode,
    statusLabel: { active: "активен", inactive: "не активен" },
    markLabel: { present: "был", absent: "не был", late: "опоздал" },
    lessonTypeLabel: { lecture: "лекция", practice: "практика" }
  };
})();
