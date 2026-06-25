(function () {
  "use strict";

  const CYCLE_222 = 6;
  const CYCLE_222_HALF = 3;

  const SHIFTS = [
    { n: 1, title: "Смена 1", sub: "бригада", kind: "day" },
    { n: 2, title: "Смена 2", sub: "бригада", kind: "night" },
    { n: 3, title: "Смена 3", sub: "бригада", kind: "day" },
    { n: 4, title: "Смена 4", sub: "бригада", kind: "night" },
  ];

  const DAY_STATES = [
    { id: "day", label: "Д", title: "Дневная", picker: "Дневная" },
    { id: "night", label: "Н", title: "Ночная", picker: "Ночная" },
    { id: "extra_day", label: "Д+", title: "Дневная доп", picker: "Дневная доп" },
    { id: "extra_night", label: "Н+", title: "Ночная доп", picker: "Ночная доп" },
    { id: "off", label: "В", title: "Выходной", picker: "Выходной" },
  ];

  const WORKING_STATES = new Set(["day", "night", "extra_day", "extra_night", "work", "extra"]);
  const CAL_HEAD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];

  function fmtLocalDate(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  function isManualPattern(pattern) {
    const cycle = (parseInt(pattern.work_days, 10) || 0) + (parseInt(pattern.off_days, 10) || 0);
    return cycle <= 0;
  }

  function shiftAnchorDate(pattern, shiftNumber) {
    const base = String(pattern.anchor_date || "").slice(0, 10);
    const sn = parseInt(shiftNumber, 10) || 1;
    const d = new Date((base || fmtLocalDate(new Date())) + "T12:00:00");
    if (sn === 3 || sn === 4) {
      d.setDate(d.getDate() + CYCLE_222_HALF);
    }
    return fmtLocalDate(d);
  }

  function cyclePosition222(pattern, dateStr, shiftNumber) {
    const anchor = new Date(shiftAnchorDate(pattern, shiftNumber) + "T12:00:00");
    const target = new Date(dateStr + "T12:00:00");
    const delta = Math.round((target - anchor) / 86400000);
    return ((delta % CYCLE_222) + CYCLE_222) % CYCLE_222;
  }

  function formulaState222(pattern, dateStr, shiftNumber) {
    const pos = cyclePosition222(pattern, dateStr, shiftNumber);
    if (pos < 2) return "day";
    if (pos >= 4) return "night";
    return "off";
  }

  function normalizeState(state, period) {
    const s = String(state || "").trim();
    if (s === "work") return period === "night" ? "night" : "day";
    if (s === "extra") return period === "night" ? "extra_night" : "extra_day";
    if (DAY_STATES.some(x => x.id === s)) return s;
    if (s === "off" || s === "auto" || !s) return s || "auto";
    return s;
  }

  function shiftLabel(shiftNumber) {
    const s = SHIFTS.find(x => x.n === parseInt(shiftNumber, 10));
    return s ? s.title : "Смена " + shiftNumber;
  }

  function shiftShort(shiftNumber) {
    const s = SHIFTS.find(x => x.n === parseInt(shiftNumber, 10));
    return s ? "С" + s.n : "С" + shiftNumber;
  }

  function stateMeta(state) {
    return DAY_STATES.find(x => x.id === state) || null;
  }

  function statusLabel(state) {
    const meta = stateMeta(state);
    if (meta) return meta.title.toLowerCase();
    if (state === "auto") return "по графику";
    return state || "не задано";
  }

  function isWorkingState(state) {
    return WORKING_STATES.has(state);
  }

  function overrideMode(getOverrideMode, patternId, dateStr, shiftNumber) {
    return normalizeState(getOverrideMode(patternId, dateStr, shiftNumber)) || "auto";
  }

  function effectiveState(getOverrideMode, pattern, dateStr, shiftNumber) {
    const mode = overrideMode(getOverrideMode, pattern.id, dateStr, shiftNumber);
    if (mode !== "auto") return mode;
    if (isManualPattern(pattern)) return "auto";
    return formulaState222(pattern, dateStr, shiftNumber);
  }

  function effectiveWorkDay(getOverrideMode, pattern, dateStr, shiftNumber) {
    const st = effectiveState(getOverrideMode, pattern, dateStr, shiftNumber);
    if (st === "auto") return false;
    return isWorkingState(st);
  }

  function cellClass(getOverrideMode, pattern, dateStr, shiftNumber) {
    const mode = overrideMode(getOverrideMode, pattern.id, dateStr, shiftNumber);
    const effective = effectiveState(getOverrideMode, pattern, dateStr, shiftNumber);
    const st = mode === "auto" ? effective : mode;
    const stateKey = st === "auto" ? "unset" : st.replace("_", "-");
    return "smu-cal-cell smu-cal-clickable smu-cal-day-cell smu-st-" + stateKey;
  }

  function cellTitle(getOverrideMode, pattern, dateStr, shiftNumber) {
    const mode = overrideMode(getOverrideMode, pattern.id, dateStr, shiftNumber);
    const effective = effectiveState(getOverrideMode, pattern, dateStr, shiftNumber);
    const st = mode === "auto" ? effective : mode;
    const meta = stateMeta(st === "auto" ? null : st);
    const label = meta ? meta.title : (isManualPattern(pattern) ? "не задано" : statusLabel(formulaState222(pattern, dateStr, shiftNumber)));
    const src = mode === "auto" ? (isManualPattern(pattern) ? "" : " · по графику") : " · вручную";
    return label + src + " · клик — изменить";
  }

  function renderShiftCalendarGrid(pattern, monthVal, shiftNumber, ctx) {
    if (!pattern || !monthVal) return "";
    const getMode = ctx.getOverrideMode;
    const today = ctx.localDateStr(new Date());
    const selected = ctx.selectedDate || null;
    const [y, m] = monthVal.split("-").map(Number);
    const lastDay = new Date(y, m, 0).getDate();
    const pad = (new Date(y, m - 1, 1).getDay() + 6) % 7;
    let cells = CAL_HEAD.map(d => `<div class="smu-cal-head-cell">${d}</div>`).join("");
    for (let i = 0; i < pad; i++) cells += `<div class="smu-cal-cell pad"></div>`;
    for (let day = 1; day <= lastDay; day++) {
      const ds = monthVal + "-" + String(day).padStart(2, "0");
      const cls = cellClass(getMode, pattern, ds, shiftNumber);
      const title = cellTitle(getMode, pattern, ds, shiftNumber);
      cells += `<button type="button" class="${cls}" data-smu-override-date="${ds}" data-smu-override-shift="${shiftNumber}" title="${title}"><span class="smu-cal-day">${day}</span></button>`;
    }
    const meta = SHIFTS.find(s => s.n === shiftNumber);
    const hint = cycleHint(pattern);
    return `<div class="smu-shift-cal-panel shift-${shiftNumber}">
      <div class="smu-shift-cal-head">
        <strong>${meta ? meta.title : "Смена " + shiftNumber}</strong>
        <span class="stat-mini">${hint}</span>
      </div>
      <div class="smu-cal-grid smu-cal-grid--single-shift">${cells}</div>
    </div>`;
  }

  function renderFourCalendars(pattern, monthVal, ctx) {
    return `<div class="smu-cal-quad">${SHIFTS.map(s =>
      renderShiftCalendarGrid(pattern, monthVal, s.n, ctx)
    ).join("")}</div>`;
  }

  function bindCellPick(host, pattern, onPick) {
    if (!host) return;
    host.querySelectorAll("[data-smu-override-date]").forEach(btn => {
      btn.onclick = (e) => {
        e.stopPropagation();
        onPick(pattern, btn.dataset.smuOverrideDate, parseInt(btn.dataset.smuOverrideShift, 10), btn);
      };
    });
  }

  function cycleHint(pattern) {
    if (isManualPattern(pattern)) return "2·2·2 вручную";
    return "2 д · 2 в · 2 н";
  }

  function cycleBar222Html() {
    return `<div class="smu-cycle-bar smu-cycle-bar-222">
      <span class="smu-cycle-block work">Д</span>
      <span class="smu-cycle-block work">Д</span>
      <span class="smu-cycle-block off">В</span>
      <span class="smu-cycle-block off">В</span>
      <span class="smu-cycle-block night">Н</span>
      <span class="smu-cycle-block night">Н</span>
      <span class="smu-cycle-repeat">↻</span>
    </div>`;
  }

  function pickerOptions() {
    return DAY_STATES;
  }

  window.SmuCalendars = {
    SHIFTS: SHIFTS,
    DAY_STATES: DAY_STATES,
    CYCLE_222: CYCLE_222,
    isManualPattern: isManualPattern,
    shiftNumbers: function () { return SHIFTS.map(s => s.n); },
    shiftAnchorDate: shiftAnchorDate,
    shiftLabel: shiftLabel,
    shiftShort: shiftShort,
    cyclePosition222: cyclePosition222,
    formulaState222: formulaState222,
    normalizeState: normalizeState,
    statusLabel: statusLabel,
    isWorkingState: isWorkingState,
    effectiveState: effectiveState,
    effectiveWorkDay: effectiveWorkDay,
    renderShiftCalendarGrid: renderShiftCalendarGrid,
    renderFourCalendars: renderFourCalendars,
    bindCellPick: bindCellPick,
    bindOverrideClicks: bindCellPick,
    cycleHint: cycleHint,
    cycleBar222Html: cycleBar222Html,
    pickerOptions: pickerOptions,
  };
})();
