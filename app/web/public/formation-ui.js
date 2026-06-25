(function () {
  "use strict";

  const FORMATION_CAL_HEAD = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
  const FORMATION_STATUS_LABELS = {
    ready: "Готово",
    scheduled: "Уже есть",
    blocked: "Нельзя",
    disabled: "Авто выкл",
  };
  const FORMATION_REASON_LABELS = {
    already_scheduled: "занятие уже создано",
    already_scheduled_today: "на трек уже есть занятие в этот день",
    all_instructors_busy: "все инструкторы уже ведут группу",
    groups_formed: "все ученики уже распределены",
    no_instructor: "нет инструктора на треке",
    no_members: "нет подходящих сотрудников",
    below_min_members: "меньше минимума группы",
    auto_disabled: "автоформирование выключено",
  };
  const FORMATION_TIME_CHOICES = ["12:00", "13:00", "14:00", "15:00"];

  function formationConveyorSlots() {
    if (window.D && typeof window.D.conveyorSlots === "function") {
      return window.D.conveyorSlots() || [];
    }
    if (window.HrApi && typeof window.HrApi.getConveyorSlots === "function") {
      return window.HrApi.getConveyorSlots() || [];
    }
    return [];
  }

  function formationSlotTimeLabel(slot) {
    if (!slot) return "";
    const parts = String(slot.starts_at_local || slot.name || "").slice(0, 8).split(":");
    return parts[0].padStart(2, "0") + ":" + (parts[1] || "00").padStart(2, "0");
  }

  function formationSlotIdByTime(slots, time) {
    const match = (slots || []).find(s => formationSlotTimeLabel(s) === time);
    return match ? String(match.id) : "";
  }

  function buildFormationTimeOptions(slots, selectedSlotId) {
    let selectedTime = FORMATION_TIME_CHOICES[0];
    if (selectedSlotId) {
      const current = (slots || []).find(s => String(s.id) === String(selectedSlotId));
      const label = formationSlotTimeLabel(current);
      if (FORMATION_TIME_CHOICES.includes(label)) selectedTime = label;
    }
    return FORMATION_TIME_CHOICES.map(time => {
      const slotId = formationSlotIdByTime(slots, time);
      const value = slotId || time;
      return '<option value="' + value + '"' + (time === selectedTime ? " selected" : "") + ">" + time + "</option>";
    }).join("");
  }

  function resolveFormationSlotId(rawValue) {
    const value = String(rawValue || "").trim();
    if (!value) return "";
    if (FORMATION_TIME_CHOICES.includes(value)) {
      return formationSlotIdByTime(formationConveyorSlots(), value) || value;
    }
    return value;
  }

  function localDateStr(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  function monthAdd(monthVal, delta) {
    const parts = String(monthVal || "").split("-").map(Number);
    const d = new Date(parts[0], (parts[1] || 1) - 1 + delta, 1);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
  }

  function monthBounds(monthVal) {
    const parts = String(monthVal || "").split("-").map(Number);
    const y = parts[0];
    const m = parts[1];
    const lastDay = new Date(y, m, 0).getDate();
    return {
      from: monthVal + "-01",
      to: monthVal + "-" + String(lastDay).padStart(2, "0"),
      lastDay: lastDay,
      year: y,
      month: m,
    };
  }

  function monthTitle(monthVal) {
    const parts = String(monthVal || "").split("-").map(Number);
    const d = new Date(parts[0], (parts[1] || 1) - 1, 1);
    return d.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
  }

  function formationPlanKey(item) {
    return item.track_id + ":" + item.slot_id + ":" + (item.lesson_date || "");
  }

  function formationSlotTime(slotId) {
    const slot = formationConveyorSlots().find(s => s.id === slotId);
    if (!slot || !slot.starts_at_local) return null;
    const parts = String(slot.starts_at_local).slice(0, 5).split(":");
    return parts[0].padStart(2, "0") + ":" + (parts[1] || "00").padStart(2, "0");
  }

  function planFilters(formationCmps) {
    return {
      lesson_type: formationCmps.planType?.getValue?.() || null,
      include_disabled: !!document.getElementById("formationIncludeDisabled")?.checked,
    };
  }

  async function loadFormationMonthData(state, formationCmps) {
    const monthEl = document.getElementById("formationPlanMonth");
    const month = (monthEl && monthEl.value) || state.formationPlanMonth;
    if (!month) return null;
    state.formationPlanMonth = month;
    const filters = planFilters(formationCmps);
    const plan = await window.HrApi.loadFormationPlanMonth({
      month: month,
      lesson_type: filters.lesson_type,
      include_disabled: filters.include_disabled,
    });
    state.formationMonthPlan = plan;
    return plan;
  }

  async function loadFormationDayDetail(state, formationCmps, dateStr) {
    if (!dateStr) {
      state.formationPlan = null;
      state.formationPlanDate = "";
      state.formationPlanSelected = {};
      return null;
    }
    const filters = planFilters(formationCmps);
    const plan = await window.HrApi.loadFormationPlan({
      target_date: dateStr,
      lesson_type: filters.lesson_type,
      include_disabled: filters.include_disabled,
    });
    state.formationPlan = plan;
    state.formationPlanDate = dateStr;
    const selected = {};
    (plan.items || []).forEach(item => {
      const withDate = Object.assign({}, item, { lesson_date: dateStr });
      if (item.status === "ready") selected[formationPlanKey(withDate)] = true;
    });
    state.formationPlanSelected = selected;
    return plan;
  }

  function renderFormationMonthSummary(state) {
    const summaryHost = document.getElementById("formationSummaryHost");
    if (!summaryHost) return;
    const plan = state.formationMonthPlan;
    if (!plan) {
      summaryHost.innerHTML = "";
      return;
    }
    const summary = plan.summary || {};
    summaryHost.innerHTML =
      '<span class="stat-chip">За месяц · строк: ' + (summary.total || 0) + '</span>' +
      '<span class="stat-chip ready">Готово: ' + (summary.ready || 0) + '</span>' +
      '<span class="stat-chip">Уже есть: ' + (summary.scheduled || 0) + '</span>' +
      '<span class="stat-chip blocked">Заблокировано: ' + (summary.blocked || 0) + '</span>' +
      '<span class="stat-chip">Авто выкл: ' + (summary.disabled || 0) + '</span>';
  }

  function formationDayCellClass(summary, dateStr, selectedDate, today) {
    let cls = "formation-cal-cell";
    if (!summary || !summary.total) cls += " is-empty";
    else if (summary.ready > 0) cls += " has-ready";
    else if (summary.scheduled > 0 && summary.blocked === 0 && summary.ready === 0) cls += " all-scheduled";
    else if (summary.blocked > 0) cls += " has-blocked";
    if (dateStr === selectedDate) cls += " selected";
    if (dateStr === today) cls += " today";
    return cls;
  }

  function renderFormationCalendar(state) {
    const host = document.getElementById("formationCalendarHost");
    if (!host) return;
    const plan = state.formationMonthPlan;
    if (!plan) {
      host.innerHTML = '<div class="empty">Нажмите «Обновить план», чтобы рассчитать календарь на месяц</div>';
      return;
    }
    const monthVal = state.formationPlanMonth;
    const bounds = monthBounds(monthVal);
    const byDate = {};
    (plan.days || []).forEach(day => { byDate[day.date] = day.summary || {}; });
    const today = localDateStr(new Date());
    const selected = state.formationPlanDate || "";
    const firstDow = (new Date(bounds.year, bounds.month - 1, 1).getDay() + 6) % 7;
    let cells = FORMATION_CAL_HEAD.map(h => '<div class="formation-cal-head">' + h + '</div>').join("");
    for (let i = 0; i < firstDow; i++) cells += '<div class="formation-cal-cell is-pad"></div>';
    for (let day = 1; day <= bounds.lastDay; day++) {
      const dateStr = monthVal + "-" + String(day).padStart(2, "0");
      const summary = byDate[dateStr] || {};
      const cls = formationDayCellClass(summary, dateStr, selected, today);
      const badges = [];
      if (summary.ready) badges.push('<span class="formation-cal-badge ready">' + summary.ready + " гот</span>");
      if (summary.scheduled) badges.push('<span class="formation-cal-badge scheduled">' + summary.scheduled + " есть</span>");
      if (summary.blocked) badges.push('<span class="formation-cal-badge blocked">' + summary.blocked + " блк</span>");
      cells +=
        '<button type="button" class="' + cls + '" data-formation-day="' + dateStr + '" title="' + dateStr + '">' +
        '<span class="formation-cal-daynum">' + day + '</span>' +
        (badges.length ? '<span class="formation-cal-badges">' + badges.join("") + '</span>' : "") +
        '</button>';
    }
    host.innerHTML =
      '<div class="formation-cal-wrap">' +
      '<div class="formation-cal-title">' + monthTitle(monthVal) + '</div>' +
      '<div class="formation-cal-legend">' +
      '<span><i class="dot ready"></i> есть готовые</span>' +
      '<span><i class="dot scheduled"></i> всё запланировано</span>' +
      '<span><i class="dot blocked"></i> есть блокировки</span>' +
      '</div>' +
      '<div class="formation-cal-grid">' + cells + '</div></div>';

    host.querySelectorAll("[data-formation-day]").forEach(btn => {
      btn.onclick = async function () {
        const dateStr = btn.dataset.formationDay;
        state.formationPlanDate = dateStr;
        const detailHost = document.getElementById("formationPlanHost");
        if (detailHost) detailHost.innerHTML = '<div class="empty">Загрузка дня…</div>';
        renderFormationCalendar(state);
        try {
          await loadFormationDayDetail(state, window.__formationCmpsRef, dateStr);
          renderFormationDayDetail(state);
        } catch (err) {
          if (detailHost) detailHost.innerHTML = '<div class="empty">' + (err.message || "Ошибка") + '</div>';
        }
      };
    });
  }

  function renderFormationDayDetail(state) {
    const host = document.getElementById("formationPlanHost");
    const titleHost = document.getElementById("formationDayDetailTitle");
    if (!host) return;
    const plan = state.formationPlan;
    const dateStr = state.formationPlanDate;
    if (!dateStr) {
      if (titleHost) titleHost.textContent = "Выберите день в календаре";
      host.innerHTML = '<div class="empty">Кликните по дню, чтобы увидеть треки и подбор группы</div>';
      return;
    }
    if (titleHost) {
      const d = new Date(dateStr + "T12:00:00");
      titleHost.textContent = d.toLocaleDateString("ru-RU", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    }
    if (!plan) {
      host.innerHTML = '<div class="empty">Загрузка…</div>';
      return;
    }
    const items = (plan.items || []).map(item => Object.assign({}, item, { lesson_date: dateStr }));
    if (!items.length) {
      host.innerHTML = '<div class="empty">Нет активных треков для формирования</div>';
      return;
    }
    host.innerHTML = '<div class="table-wrap"><table class="entity-table formation-plan-table"><thead><tr>' +
      '<th style="width:36px"><input type="checkbox" id="formationSelectAllReady" title="Выбрать готовые"></th>' +
      '<th>Трек / время</th><th>Инструктор</th><th>Подбор</th><th>Статус</th><th></th>' +
      '</tr></thead><tbody>' + items.map(item => {
        const key = formationPlanKey(item);
        const expanded = state.formationPlanExpanded[key];
        const canSelect = item.status === "ready";
        const checked = !!state.formationPlanSelected[key];
        const statusLabel = FORMATION_STATUS_LABELS[item.status] || item.status;
        const reason = item.reason ? (FORMATION_REASON_LABELS[item.reason] || item.reason) : "";
        return '<tr><td>' + (canSelect ? '<input type="checkbox" class="formation-plan-check" data-plan-key="' + key + '" ' + (checked ? "checked" : "") + '>' : "") + '</td>' +
          '<td><div class="plan-track">' + (item.track_name || "—") + '</div><div class="plan-meta">' +
          (item.slot_name || "—") + " · " + (item.slot_starts_at || "—") + " · " + (item.lesson_type === "lecture" ? "лекция" : "практика") + '</div></td>' +
          '<td>' + (item.teacher_name || "—") + '</td>' +
          '<td>' + (item.selected_count || 0) + " / " + (item.max_members || "—") +
          (item.reserve_count > 0 ? ' <span class="plan-meta">+' + item.reserve_count + " рез.</span>" : "") +
          (item.min_members > 1 ? " (мин. " + item.min_members + ")" : "") + '</td>' +
          '<td><span class="formation-status ' + item.status + '">' + statusLabel + '</span>' +
          (reason ? '<div class="plan-meta">' + reason + '</div>' : "") + '</td>' +
          '<td><button type="button" class="btn small secondary formation-expand-btn" data-plan-key="' + key + '">' + (expanded ? "Скрыть" : "Детали") + '</button></td></tr>' +
          (expanded ? '<tr><td colspan="6"><div class="formation-plan-detail">' +
            (item.selected && item.selected.length ? '<h5>В группу (' + item.selected.length + ')</h5><div class="table-wrap"><table><thead><tr><th>Сотрудник</th><th>Осталось</th><th>Срок до</th><th>Вес</th></tr></thead><tbody>' +
              item.selected.map(u => '<tr><td>' + u.name + '</td><td>' + u.remaining + '</td><td>' + (u.due_date || "—") + '</td><td>' + Number(u.weight || 0).toFixed(1) + '</td></tr>').join("") +
              '</tbody></table></div>' : '<div class="empty">Никого не подобрано</div>') +
            (item.excluded && item.excluded.length ? '<h5 style="margin-top:12px">Отсеяно (' + item.excluded.length + ')</h5><div class="formation-excluded-list">' +
              item.excluded.slice(0, 80).map(u => '<div>' + u.name + " — " + u.reason + '</div>').join("") + '</div>' : "") +
            (item.reserve && item.reserve.length ? '<h5 style="margin-top:12px">Резерв (' + item.reserve.length + ')</h5><div class="table-wrap"><table><thead><tr><th>Сотрудник</th><th>Осталось</th><th>Срок до</th><th>Вес</th></tr></thead><tbody>' +
              item.reserve.map(u => '<tr><td>' + u.name + '</td><td>' + u.remaining + '</td><td>' + (u.due_date || "—") + '</td><td>' + Number(u.weight || 0).toFixed(1) + '</td></tr>').join("") +
              '</tbody></table></div><p class="stat-mini" style="margin:6px 0 0">Не вошли в группу из‑за лимита ' + (item.max_members || "—") + ' чел.</p>' : "") +
            '</div></td></tr>' : "");
      }).join("") + '</tbody></table></div>';

    const selectAll = document.getElementById("formationSelectAllReady");
    if (selectAll) {
      selectAll.onchange = function () {
        items.forEach(item => {
          if (item.status === "ready") state.formationPlanSelected[formationPlanKey(item)] = selectAll.checked;
        });
        renderFormationDayDetail(state);
      };
    }
    host.querySelectorAll(".formation-plan-check").forEach(cb => {
      cb.onchange = function () {
        state.formationPlanSelected[cb.dataset.planKey] = cb.checked;
      };
    });
    host.querySelectorAll(".formation-expand-btn").forEach(btn => {
      btn.onclick = function () {
        const key = btn.dataset.planKey;
        state.formationPlanExpanded[key] = !state.formationPlanExpanded[key];
        renderFormationDayDetail(state);
      };
    });
  }

  async function refreshFormationPlan(state, formationCmps, showToast) {
    window.__formationCmpsRef = formationCmps;
    const calHost = document.getElementById("formationCalendarHost");
    const detailHost = document.getElementById("formationPlanHost");
    if (calHost) calHost.innerHTML = '<div class="empty">Расчёт календаря на месяц…</div>';
    if (detailHost && state.formationPlanDate) detailHost.innerHTML = '<div class="empty">Обновление…</div>';
    try {
      await loadFormationMonthData(state, formationCmps);
      renderFormationMonthSummary(state);
      renderFormationCalendar(state);
      if (state.formationPlanDate) {
        await loadFormationDayDetail(state, formationCmps, state.formationPlanDate);
        renderFormationDayDetail(state);
      } else {
        renderFormationDayDetail(state);
      }
    } catch (err) {
      if (calHost) calHost.innerHTML = '<div class="empty">' + (err.message || "Ошибка") + '</div>';
      showToast(err.message || "Ошибка расчёта плана", "error");
    }
  }

  async function createFormationFromPlan(state, formationCmps, selectedOnly, showToast, reloadData, renderLessons) {
    const date = state.formationPlanDate;
    if (!date) return showToast("Выберите день в календаре", "warning");
    let items = null;
    if (selectedOnly) {
      items = Object.keys(state.formationPlanSelected)
        .filter(k => state.formationPlanSelected[k])
        .map(k => {
          const parts = k.split(":");
          return { track_id: parts[0], slot_id: parts[1], lesson_date: parts[2] || date };
        });
      if (!items.length) return showToast('Выберите строки со статусом «Готово»', "warning");
    }
    try {
      const res = await window.HrApi.createFormationPlan({
        target_date: date,
        items: items || [],
        lesson_type: formationCmps.planType?.getValue?.() || null,
      });
      await reloadData();
      const n = (res.created || []).length;
      showToast(n ? "Создано занятий: " + n : "Новых занятий не создано", n ? "success" : "warning");
      await refreshFormationPlan(state, formationCmps, showToast);
      renderLessons?.(true);
    } catch (err) {
      showToast(err.message || "Ошибка создания", "error");
    }
  }

  async function createFormationMonthReady(state, formationCmps, showToast, reloadData, renderLessons) {
    const month = state.formationPlanMonth || document.getElementById("formationPlanMonth")?.value;
    if (!month) return showToast("Укажите месяц", "warning");
    if (!confirm("Создать все готовые занятия за " + monthTitle(month) + "?")) return;
    try {
      const res = await window.HrApi.createFormationPlanMonth({
        month: month,
        items: [],
        lesson_type: formationCmps.planType?.getValue?.() || null,
      });
      await reloadData();
      const n = (res.created || []).length;
      showToast(n ? "Создано занятий за месяц: " + n : "Новых занятий не создано", n ? "success" : "warning");
      await refreshFormationPlan(state, formationCmps, showToast);
      renderLessons?.(true);
    } catch (err) {
      showToast(err.message || "Ошибка создания", "error");
    }
  }

  async function renderFormationLog(showToast) {
    const host = document.getElementById("formationLogHost");
    if (!host) return;
    host.innerHTML = '<div class="empty">Загрузка журнала…</div>';
    try {
      const from = document.getElementById("formationLogFrom")?.value || null;
      const to = document.getElementById("formationLogTo")?.value || null;
      const rows = await window.HrApi.loadFormationLog({ from_date: from, to_date: to, limit: 150 });
      if (!rows.length) {
        host.innerHTML = '<div class="empty">Записей пока нет</div>';
        return;
      }
      host.innerHTML = '<div class="table-wrap"><table class="entity-table"><thead><tr><th>Когда</th><th>Дата занятия</th><th>Трек</th><th>Слот</th><th>Статус</th><th>Детали</th></tr></thead><tbody>' +
        rows.map(row => '<tr><td>' + String(row.created_at || "").slice(0, 16).replace("T", " ") + '</td><td>' +
          String(row.lesson_date || "").slice(0, 10) + '</td><td>' + (row.track_name || "—") + '</td><td>' +
          (row.slot_name || "—") + '</td><td>' + (row.status || "—") + '</td><td>' + (row.detail || "—") + '</td></tr>').join("") +
        '</tbody></table></div>';
    } catch (err) {
      host.innerHTML = '<div class="empty">' + (err.message || "Ошибка") + '</div>';
    }
  }

  async function renderTrackFormationSettings(trackId, hostId, I, showToast) {
    const host = document.getElementById(hostId || "trackFormationSettingsHost");
    if (!host) return;
    host.className = "track-formation-settings-host";
    host.innerHTML = '<div class="empty">Загрузка…</div>';
    try {
      const settings = await window.HrApi.loadTrackFormationSettings(trackId);
      if (!host.isConnected) return;
      const slots = formationConveyorSlots();
      const selectedId = (settings.formation_slot_ids || [])[0] || formationSlotIdByTime(slots, FORMATION_TIME_CHOICES[0]) || "";
      const timeOptions = buildFormationTimeOptions(slots, selectedId);
      const placeVal = String(settings.formation_default_place || "")
        .replace(/&/g, "&amp;")
        .replace(/"/g, "&quot;")
        .replace(/</g, "&lt;");

      host.className = "formation-settings-grid";
      host.innerHTML =
        '<div class="formation-settings-toggle">' +
          '<label class="formation-settings-check">' +
            '<input type="checkbox" id="tfAutoEnabled"' + (settings.formation_auto_enabled !== false ? " checked" : "") + ">" +
            "<span><strong>Автоформирование</strong>" +
            "<small>Автоматически создавать занятия по этому треку в выбранный слот</small></span>" +
          "</label>" +
        "</div>" +
        '<div class="formation-settings-field"><label class="ui-label" for="tfLessonType">Тип занятия</label>' +
        '<select id="tfLessonType" class="cell-input">' +
        '<option value="practice"' + (settings.formation_lesson_type === "practice" ? " selected" : "") + ">Практика</option>" +
        '<option value="lecture"' + (settings.formation_lesson_type === "lecture" ? " selected" : "") + ">Лекция</option></select></div>" +
        '<div class="formation-settings-field"><label class="ui-label" for="tfLessonTime">Время занятия</label>' +
        '<select id="tfLessonTime" class="cell-input">' + timeOptions + "</select></div>" +
        '<div class="formation-settings-field"><label class="ui-label" for="tfMaxMembers">Макс. в группе</label>' +
        '<input type="number" id="tfMaxMembers" class="cell-input" min="1" max="50" value="' + (settings.formation_max_members || 12) + '"></div>' +
        '<div class="formation-settings-field"><label class="ui-label" for="tfMinMembers">Мин. в группе</label>' +
        '<input type="number" id="tfMinMembers" class="cell-input" min="1" max="50" value="' + (settings.formation_min_members || 1) + '"></div>' +
        '<div class="formation-settings-field formation-settings-field--wide"><label class="ui-label" for="tfDefaultPlace">Место</label>' +
        '<input type="text" id="tfDefaultPlace" class="cell-input" value="' + placeVal + '" placeholder="Площадка · направление"></div>' +
        '<div class="formation-settings-actions"><button type="button" class="btn" id="saveTrackFormationBtn">' + I("check") + " Сохранить</button></div>";

      document.getElementById("saveTrackFormationBtn").onclick = async function () {
        const slotEl = document.getElementById("tfLessonTime");
        const slotId = resolveFormationSlotId(slotEl && slotEl.value);
        if (!slotId || FORMATION_TIME_CHOICES.includes(slotId)) {
          showToast("Не удалось сохранить время. Обновите страницу.", "warning");
          return;
        }
        const slotIds = [slotId];
        try {
          await window.HrApi.updateTrackFormationSettings(trackId, {
            formation_auto_enabled: document.getElementById("tfAutoEnabled").checked,
            formation_lesson_type: document.getElementById("tfLessonType").value,
            formation_max_members: parseInt(document.getElementById("tfMaxMembers").value, 10) || 12,
            formation_min_members: parseInt(document.getElementById("tfMinMembers").value, 10) || 1,
            formation_default_place: (document.getElementById("tfDefaultPlace").value || "").trim() || null,
            clear_default_place: !(document.getElementById("tfDefaultPlace").value || "").trim(),
            slot_ids: slotIds,
          });
          showToast("Настройки сохранены", "success");
        } catch (err) { showToast(err.message || "Ошибка", "error"); }
      };
    } catch (err) {
      if (!host.isConnected) return;
      host.className = "track-formation-settings-host";
      host.innerHTML = '<div class="empty">' + (err.message || "Ошибка загрузки") + "</div>";
    }
  }

  window.FormationUi = {
    formationTimeChoices: function () { return FORMATION_TIME_CHOICES.slice(); },
    resolveSlotIdForTime: resolveFormationSlotId,
    formationSlotTime: formationSlotTime,
    monthAdd: monthAdd,
    refreshFormationPlan: refreshFormationPlan,
    renderFormationMonthSummary: renderFormationMonthSummary,
    renderFormationCalendar: renderFormationCalendar,
    renderFormationDayDetail: renderFormationDayDetail,
    createFormationFromPlan: createFormationFromPlan,
    createFormationMonthReady: createFormationMonthReady,
    renderFormationLog: renderFormationLog,
    renderTrackFormationSettings: renderTrackFormationSettings,
  };
})();
