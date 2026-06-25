(function () {
  "use strict";

  const SHIFTS = [
    { n: 1, title: "Смена 1", sub: "День", kind: "day" },
    { n: 2, title: "Смена 2", sub: "Ночь", kind: "night" },
    { n: 3, title: "Смена 3", sub: "День", kind: "day" },
    { n: 4, title: "Смена 4", sub: "Ночь", kind: "night" },
  ];

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
    const work = parseInt(pattern.work_days, 10) || 0;
    const off = parseInt(pattern.off_days, 10) || 0;
    const cycle = work + off;
    const sn = parseInt(shiftNumber, 10) || 1;
    const d = new Date((base || fmtLocalDate(new Date())) + "T12:00:00");
    if (sn === 3 || sn === 4) {
      d.setDate(d.getDate() + (cycle > 0 ? Math.floor(cycle / 2) : work));
    }
    return fmtLocalDate(d);
  }

  function shiftLabel(shiftNumber) {
    const s = SHIFTS.find(x => x.n === parseInt(shiftNumber, 10));
    return s ? `${s.title} · ${s.sub}` : `Смена ${shiftNumber}`;
  }

  function shiftShort(shiftNumber) {
    const s = SHIFTS.find(x => x.n === parseInt(shiftNumber, 10));
    return s ? `С${s.n}` : `С${shiftNumber}`;
  }

  function isWorkDayFormula(pattern, dateStr, shiftNumber) {
    if (isManualPattern(pattern)) return false;
    const work = pattern.work_days || 0;
    const off = pattern.off_days || 0;
    const cycle = work + off;
    if (cycle <= 0) return false;
    const anchor = new Date(shiftAnchorDate(pattern, shiftNumber) + "T12:00:00");
    const target = new Date(dateStr + "T12:00:00");
    const delta = Math.round((target - anchor) / 86400000);
    const pos = ((delta % cycle) + cycle) % cycle;
    return pos < work;
  }

  function nextOverrideState(current) {
    if (!current || current === "auto") return "work";
    if (current === "work") return "off";
    if (current === "off") return "extra";
    return "auto";
  }

  function overrideMode(getOverrideMode, patternId, dateStr, shiftNumber) {
    return getOverrideMode(patternId, dateStr, shiftNumber) || "auto";
  }

  function effectiveWorkDay(getOverrideMode, pattern, dateStr, shiftNumber) {
    const mode = overrideMode(getOverrideMode, pattern.id, dateStr, shiftNumber);
    if (mode === "extra" || mode === "work") return true;
    if (mode === "off") return false;
    return isWorkDayFormula(pattern, dateStr, shiftNumber);
  }

  function cellClass(getOverrideMode, pattern, dateStr, shiftNumber, today, selectedDate) {
    const mode = overrideMode(getOverrideMode, pattern.id, dateStr, shiftNumber);
    const working = effectiveWorkDay(getOverrideMode, pattern, dateStr, shiftNumber);
    let cls = "smu-shift-cal-cell shift-" + shiftNumber;
    if (mode === "extra") cls += " is-extra";
    else if (mode === "work") cls += " is-force-work";
    else if (mode === "off") cls += " is-force-off";
    else if (isManualPattern(pattern)) cls += " is-empty";
    else cls += working ? " is-work" : " is-off";
    if (dateStr === selectedDate) cls += " selected";
    if (dateStr === today) cls += " today";
    return cls;
  }

  function cycleHint(pattern) {
    if (isManualPattern(pattern)) return "вручную";
    const w = pattern.work_days || 2;
    const o = pattern.off_days || 2;
    return w + " д · " + o + " в";
  }

  function cellTitle(getOverrideMode, pattern, dateStr, shiftNumber) {
    const mode = overrideMode(getOverrideMode, pattern.id, dateStr, shiftNumber);
    const labels = {
      auto: isManualPattern(pattern) ? "не задано" : "по графику",
      work: "рабочий",
      off: "выходной",
      extra: "допсмена",
    };
    return labels[mode] || labels.auto;
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
      const ds = `${monthVal}-${String(day).padStart(2, "0")}`;
      const cls = cellClass(getMode, pattern, ds, shiftNumber, today, selected);
      const title = cellTitle(getMode, pattern, ds, shiftNumber);
      cells += `<button type="button" class="${cls}" data-smu-override-date="${ds}" data-smu-override-shift="${shiftNumber}" title="${title}">${day}</button>`;
    }
    const meta = SHIFTS.find(s => s.n === shiftNumber);
    const hint = isManualPattern(pattern) ? "заполните вручную" : cycleHint(pattern);
    return `<div class="smu-shift-cal-panel shift-${shiftNumber}">
      <div class="smu-shift-cal-head">
        <strong>${meta ? meta.title : "Смена " + shiftNumber}</strong>
        <span class="stat-mini">${meta ? meta.sub : ""} · ${hint}</span>
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
        onPick(
          pattern,
          btn.dataset.smuOverrideDate,
          parseInt(btn.dataset.smuOverrideShift, 10),
          btn
        );
      };
    });
  }

  window.SmuCalendars = {
    SHIFTS: SHIFTS,
    isManualPattern: isManualPattern,
    shiftNumbers: function () { return SHIFTS.map(s => s.n); },
    shiftAnchorDate: shiftAnchorDate,
    shiftLabel: shiftLabel,
    shiftShort: shiftShort,
    isWorkDayFormula: isWorkDayFormula,
    nextOverrideState: nextOverrideState,
    effectiveWorkDay: effectiveWorkDay,
    renderShiftCalendarGrid: renderShiftCalendarGrid,
    renderFourCalendars: renderFourCalendars,
    bindCellPick: bindCellPick,
    bindOverrideClicks: bindCellPick,
    cycleHint: cycleHint,
  };
})();
