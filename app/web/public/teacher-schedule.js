(function (global) {
  "use strict";

  var CAL_DAY_START = 8 * 60;
  var CAL_DAY_END = 20 * 60;
  var PX_PER_MIN = 1.2;
  var MIN_BLOCK_PX = 28;

  function lessonDateStr(lesson) {
    if (lesson.date) return lesson.date;
    if (!lesson.startsAt) return "";
    var d = new Date(lesson.startsAt);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  function startMinutes(lesson) {
    if (lesson.startsAt) {
      var d = new Date(lesson.startsAt);
      return d.getHours() * 60 + d.getMinutes();
    }
    if (lesson.time) {
      var p = lesson.time.split(":").map(Number);
      return p[0] * 60 + p[1];
    }
    return CAL_DAY_START;
  }

  function endMinutes(lesson) {
    if (lesson.endsAt) {
      var d = new Date(lesson.endsAt);
      return d.getHours() * 60 + d.getMinutes();
    }
    if (lesson.timeEnd) {
      var p = lesson.timeEnd.split(":").map(Number);
      return p[0] * 60 + p[1];
    }
    return startMinutes(lesson) + 60;
  }

  function minutesToLabel(m) {
    return String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");
  }

  function lessonsOverlap(l1, l2) {
    if (lessonDateStr(l1) !== lessonDateStr(l2)) return false;
    var s1 = l1.startsAt ? new Date(l1.startsAt).getTime() : 0;
    var e1 = l1.endsAt ? new Date(l1.endsAt).getTime() : 0;
    var s2 = l2.startsAt ? new Date(l2.startsAt).getTime() : 0;
    var e2 = l2.endsAt ? new Date(l2.endsAt).getTime() : 0;
    if (!s1 || !e1 || !s2 || !e2) return false;
    return s1 < e2 && s2 < e1;
  }

  function studentIdsOf(lesson, ctx) {
    if (lesson.studentIds && lesson.studentIds.length) return lesson.studentIds;
    if (ctx && ctx.lessonStudents) return ctx.lessonStudents(lesson).map(function (u) { return u.id; });
    return [];
  }

  function comparePairConflicts(a, b, ctx) {
    var reasons = [];
    if (!lessonsOverlap(a, b)) return reasons;
    var teacherId = ctx.teacherId;
    var involvesMe = a.id_teacher === teacherId || b.id_teacher === teacherId;
    if (!involvesMe) return reasons;

    if (a.id_teacher === teacherId && b.id_teacher === teacherId) {
      reasons.push("╨Ф╨▓╨╛╨╣╨╜╨╛╨╡ ╨▒╤А╨╛╨╜╨╕╤А╨╛╨▓╨░╨╜╨╕╨╡: " + (b.title || "╨╖╨░╨╜╤П╤В╨╕╨╡"));
    }
    var placeA = (a.place || "").trim().toLowerCase();
    var placeB = (b.place || "").trim().toLowerCase();
    if (placeA && placeB && placeA === placeB) {
      reasons.push("╨Ъ╨░╨▒╨╕╨╜╨╡╤В ╨╖╨░╨╜╤П╤В: " + (a.place || b.place));
    }
    if (a.id_group && b.id_group && a.id_group === b.id_group) {
      var gname = ctx.groupById ? (ctx.groupById(a.id_group)?.name || "╨│╤А╤Г╨┐╨┐╨░") : "╨│╤А╤Г╨┐╨┐╨░";
      reasons.push("╨У╤А╤Г╨┐╨┐╨░ ╨╖╨░╨╜╤П╤В╨░: " + gname);
    }
    var idsA = studentIdsOf(a, ctx);
    var idsB = studentIdsOf(b, ctx);
    var shared = idsA.filter(function (id) { return idsB.indexOf(id) >= 0; });
    if (shared.length && ctx.fullName && ctx.userById) {
      reasons.push("╨г╤З╨╡╨╜╨╕╨║(╨╕) ╨╖╨░╨╜╤П╤В╤Л: " + shared.map(function (id) {
        return ctx.fullName(ctx.userById(id));
      }).join(", "));
    }
    return reasons;
  }

  function detectConflicts(lesson, allLessons, ctx) {
    var reasons = [];
    var seen = {};
    (allLessons || []).forEach(function (other) {
      if (!other || other.id === lesson.id) return;
      comparePairConflicts(lesson, other, ctx).forEach(function (r) {
        if (!seen[r]) { seen[r] = true; reasons.push(r); }
      });
    });
    return { hasConflict: reasons.length > 0, reasons: reasons };
  }

  function lessonShowsInConflictsFilter(lesson, allLessons, ctx) {
    var self = detectConflicts(lesson, allLessons, ctx);
    if (self.hasConflict) return true;
    if (lesson.id_teacher === ctx.teacherId) return false;
    return (allLessons || []).some(function (mine) {
      if (mine.id_teacher !== ctx.teacherId) return false;
      if (!lessonsOverlap(lesson, mine)) return false;
      return detectConflicts(mine, allLessons, ctx).hasConflict;
    });
  }

  function filterByScheduleMode(lessons, mode, teacherId, ctx) {
    if (mode === "mine") {
      return lessons.filter(function (l) { return l.id_teacher === teacherId; });
    }
    if (mode === "conflicts") {
      return lessons.filter(function (l) { return lessonShowsInConflictsFilter(l, lessons, ctx); });
    }
    return lessons;
  }

  function mergeOverlapGroups(lessons) {
    var groups = lessons.map(function (l) { return [l]; });
    var merged = true;
    while (merged) {
      merged = false;
      outer: for (var i = 0; i < groups.length; i++) {
        for (var j = i + 1; j < groups.length; j++) {
          var touch = groups[i].some(function (a) {
            return groups[j].some(function (b) { return lessonsOverlap(a, b); });
          });
          if (touch) {
            groups[i] = groups[i].concat(groups[j]);
            groups.splice(j, 1);
            merged = true;
            break outer;
          }
        }
      }
    }
    return groups;
  }

  function packGroupLanes(group) {
    var sorted = group.slice().sort(function (a, b) {
      return new Date(a.startsAt) - new Date(b.startsAt);
    });
    var lanes = [];
    var laneById = {};
    sorted.forEach(function (lesson) {
      var lane = 0;
      while (lane < lanes.length) {
        var busy = lanes[lane].some(function (l) { return lessonsOverlap(l, lesson); });
        if (!busy) break;
        lane += 1;
      }
      if (!lanes[lane]) lanes[lane] = [];
      lanes[lane].push(lesson);
      laneById[lesson.id] = lane;
    });
    return { laneById: laneById, laneCount: Math.max(lanes.length, 1) };
  }

  function layoutDayLessons(dayLessons, dayStartMin, pxPerMin) {
    if (!dayLessons.length) return [];
    var groups = mergeOverlapGroups(dayLessons);
    var blocks = [];
    groups.forEach(function (group) {
      var pack = packGroupLanes(group);
      group.forEach(function (lesson) {
        var start = Math.max(startMinutes(lesson), dayStartMin);
        var end = Math.min(endMinutes(lesson), CAL_DAY_END);
        if (end <= start) return;
        var lane = pack.laneById[lesson.id];
        var laneCount = pack.laneCount;
        blocks.push({
          lesson: lesson,
          top: (start - dayStartMin) * pxPerMin,
          height: Math.max((end - start) * pxPerMin, MIN_BLOCK_PX),
          leftPct: (lane / laneCount) * 100,
          widthPct: (100 / laneCount) - 0.5,
        });
      });
    });
    return blocks;
  }

  function totalHeightPx(dayStartMin, dayEndMin, pxPerMin) {
    return (dayEndMin - dayStartMin) * pxPerMin;
  }

  function hourMarkers(dayStartMin, dayEndMin) {
    var markers = [];
    for (var m = dayStartMin; m <= dayEndMin; m += 60) {
      markers.push({ min: m, label: minutesToLabel(m), top: (m - dayStartMin) * PX_PER_MIN });
    }
    return markers;
  }

  function validateDraft(draft, allLessons, excludeId, ctx) {
    var pseudo = Object.assign({}, draft, {
      id: excludeId || "__draft__",
      id_teacher: ctx.teacherId,
      id_group: draft.id_group,
      place: draft.place,
      startsAt: draft.startsAt,
      endsAt: draft.endsAt,
      date: draft.date,
      studentIds: draft.studentIds,
      title: draft.title || "╨Ч╨░╨╜╤П╤В╨╕╨╡",
    });
    var errors = detectConflicts(pseudo, (allLessons || []).filter(function (l) {
      return String(l.id) !== String(excludeId);
    }), ctx).reasons;
    if (draft.endsAt && draft.startsAt && new Date(draft.endsAt) <= new Date(draft.startsAt)) {
      errors.push("╨Т╤А╨╡╨╝╤П ╨╛╨║╨╛╨╜╤З╨░╨╜╨╕╤П ╨┤╨╛╨╗╨╢╨╜╨╛ ╨▒╤Л╤В╤М ╨┐╨╛╨╖╨╢╨╡ ╨╜╨░╤З╨░╨╗╨░");
    }
    return errors;
  }

  function adjacentWithConflicts(draft, allLessons, excludeId, ctx) {
    var pseudo = {
      id: excludeId || "__draft__",
      id_teacher: ctx.teacherId,
      date: draft.date,
      startsAt: draft.startsAt,
      endsAt: draft.endsAt,
      place: draft.place,
      id_group: draft.id_group,
      studentIds: draft.studentIds,
      title: draft.title,
    };
    return (allLessons || []).filter(function (l) {
      return String(l.id) !== String(excludeId) && l.id_teacher !== ctx.teacherId && lessonsOverlap(pseudo, l);
    }).map(function (l) {
      var reasons = comparePairConflicts(pseudo, l, ctx);
      return { lesson: l, reasons: reasons };
    });
  }

  global.TeacherSchedule = {
    CAL_DAY_START: CAL_DAY_START,
    CAL_DAY_END: CAL_DAY_END,
    PX_PER_MIN: PX_PER_MIN,
    lessonDateStr: lessonDateStr,
    startMinutes: startMinutes,
    endMinutes: endMinutes,
    minutesToLabel: minutesToLabel,
    lessonsOverlap: lessonsOverlap,
    detectConflicts: detectConflicts,
    lessonShowsInConflictsFilter: lessonShowsInConflictsFilter,
    filterByScheduleMode: filterByScheduleMode,
    layoutDayLessons: layoutDayLessons,
    totalHeightPx: totalHeightPx,
    hourMarkers: hourMarkers,
    validateDraft: validateDraft,
    adjacentWithConflicts: adjacentWithConflicts,
    comparePairConflicts: comparePairConflicts,
  };
})(window);
