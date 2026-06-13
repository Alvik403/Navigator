/* MAX RASS — кастомные UI-компоненты (select, date, time) */
(function (global) {
  "use strict";

  function menuOf(root) {
    return root.querySelector(".ui-menu");
  }

  function anchorOf(root) {
    return root.querySelector(".ui-trigger, .ui-search-trigger");
  }

  function shouldFloatMenu(root) {
    return !!root.closest(".overlay, .modal-overlay, .modal, .modal-scroll, .preview-table, .ge-col-body, .table-wrap");
  }

  function resetFloatingMenu(menu) {
    if (!menu) return;
    menu.classList.remove("ui-menu-floating");
    menu.style.cssText = "";
  }

  function floatMenu(root, menu) {
    const anchor = anchorOf(root);
    if (!anchor || !menu) return;
    const rect = anchor.getBoundingClientRect();
    const maxH = menu.classList.contains("ui-cal-menu") ? 360 : 240;
    menu.classList.add("ui-menu-floating");
    menu.style.display = "block";
    menu.style.position = "fixed";
    menu.style.left = rect.left + "px";
    menu.style.width = rect.width + "px";
    menu.style.minWidth = rect.width + "px";
    menu.style.zIndex = "1200";
    menu.style.maxHeight = maxH + "px";
    const height = Math.min(maxH, menu.scrollHeight || maxH);
    let top = rect.bottom + 4;
    if (top + height > window.innerHeight - 8) {
      top = Math.max(8, rect.top - height - 4);
    }
    menu.style.top = top + "px";
  }

  function openDropdown(root) {
    root.classList.add("open");
    const menu = menuOf(root);
    if (shouldFloatMenu(root)) {
      requestAnimationFrame(() => floatMenu(root, menu));
    }
  }

  function closeDropdown(root) {
    root.classList.remove("open");
    resetFloatingMenu(menuOf(root));
  }

  function closeAll(except) {
    document.querySelectorAll(".ui-dropdown.open").forEach(el => {
      if (el !== except) closeDropdown(el);
    });
  }

  document.addEventListener("click", () => closeAll(null));
  document.addEventListener("scroll", () => {
    document.querySelectorAll(".ui-dropdown.open").forEach(root => {
      const menu = menuOf(root);
      if (menu?.classList.contains("ui-menu-floating")) floatMenu(root, menu);
    });
  }, true);
  window.addEventListener("resize", () => {
    document.querySelectorAll(".ui-dropdown.open").forEach(root => {
      const menu = menuOf(root);
      if (menu?.classList.contains("ui-menu-floating")) floatMenu(root, menu);
    });
  });

  function mountField(container, label) {
    container.innerHTML = "";
    const wrap = document.createElement("div");
    wrap.className = "ui-field";
    if (label) {
      const lbl = document.createElement("label");
      lbl.className = "ui-label";
      lbl.textContent = label;
      wrap.appendChild(lbl);
    }
    container.appendChild(wrap);
    return wrap;
  }

  function createSelect(container, opts) {
    const { label, options = [], value = "", placeholder = "Выберите", onChange } = opts;
    const wrap = mountField(container, label);
    const root = document.createElement("div");
    root.className = "ui-select ui-dropdown";
    root.innerHTML = `
      <button type="button" class="ui-trigger">
        <span class="ui-trigger-text"></span>
        <span class="ui-chevron"></span>
      </button>
      <div class="ui-menu"></div>`;
    wrap.appendChild(root);

    const trigger = root.querySelector(".ui-trigger");
    const textEl = root.querySelector(".ui-trigger-text");
    const menu = root.querySelector(".ui-menu");
    let current = value;

    function renderMenu() {
      menu.innerHTML = options.map(o => `
        <button type="button" class="ui-option ${o.value === current ? "active" : ""}" data-value="${o.value}">
          ${o.label}
        </button>`).join("");
      menu.querySelectorAll(".ui-option").forEach(btn => {
        btn.onclick = (e) => {
          e.stopPropagation();
          current = btn.dataset.value;
          updateText();
          closeDropdown(root);
          onChange && onChange(current);
        };
      });
    }

    function updateText() {
      const found = options.find(o => String(o.value) === String(current));
      textEl.textContent = found ? found.label : placeholder;
      textEl.classList.toggle("placeholder", !found);
    }

    trigger.onclick = (e) => {
      e.stopPropagation();
      const open = root.classList.contains("open");
      closeAll(null);
      if (!open) {
        renderMenu();
        openDropdown(root);
      }
    };

    updateText();

    return {
      getValue: () => current,
      setValue: (v) => { current = v; updateText(); },
      setOptions: (arr) => { options.length = 0; arr.forEach(o => options.push(o)); updateText(); },
      destroy: () => { wrap.remove(); }
    };
  }

  function pad(n) { return String(n).padStart(2, "0"); }

  function parseDateStr(s) {
    if (!s) return new Date();
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
  }

  function toDateStr(d) {
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }

  function createDatePicker(container, opts) {
    const { label, value = toDateStr(new Date()), onChange } = opts;
    const wrap = mountField(container, label);
    const root = document.createElement("div");
    root.className = "ui-datepicker ui-dropdown";
    let viewDate = parseDateStr(value);
    let current = value;

    root.innerHTML = `
      <button type="button" class="ui-trigger">
        <span class="ui-icon-cal"></span>
        <span class="ui-trigger-text"></span>
        <span class="ui-chevron"></span>
      </button>
      <div class="ui-menu ui-cal-menu"></div>`;
    wrap.appendChild(root);

    const trigger = root.querySelector(".ui-trigger");
    const textEl = root.querySelector(".ui-trigger-text");
    const menu = root.querySelector(".ui-cal-menu");
    const weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

    function updateText() {
      const d = parseDateStr(current);
      textEl.textContent = d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
    }

    function renderCal() {
      const y = viewDate.getFullYear();
      const m = viewDate.getMonth();
      const first = new Date(y, m, 1);
      const startDay = (first.getDay() + 6) % 7;
      const daysInMonth = new Date(y, m + 1, 0).getDate();
      const today = toDateStr(new Date());

      let cells = "";
      for (let i = 0; i < startDay; i++) cells += `<span class="ui-cal-empty"></span>`;
      for (let d = 1; d <= daysInMonth; d++) {
        const ds = y + "-" + pad(m + 1) + "-" + pad(d);
        const cls = ["ui-cal-day"];
        if (ds === current) cls.push("active");
        if (ds === today) cls.push("today");
        cells += `<button type="button" class="${cls.join(" ")}" data-date="${ds}">${d}</button>`;
      }

      menu.innerHTML = `
        <div class="ui-cal-head">
          <button type="button" class="ui-cal-nav" data-nav="-1">‹</button>
          <span>${viewDate.toLocaleDateString("ru-RU", { month: "long", year: "numeric" })}</span>
          <button type="button" class="ui-cal-nav" data-nav="1">›</button>
        </div>
        <div class="ui-cal-weekdays">${weekdays.map(w => `<span>${w}</span>`).join("")}</div>
        <div class="ui-cal-grid">${cells}</div>`;

      menu.querySelectorAll(".ui-cal-nav").forEach(btn => {
        btn.onclick = (e) => {
          e.stopPropagation();
          viewDate.setMonth(viewDate.getMonth() + +btn.dataset.nav);
          renderCal();
        };
      });
      menu.querySelectorAll(".ui-cal-day").forEach(btn => {
        btn.onclick = (e) => {
          e.stopPropagation();
          current = btn.dataset.date;
          updateText();
          closeDropdown(root);
          onChange && onChange(current);
        };
      });
    }

    trigger.onclick = (e) => {
      e.stopPropagation();
      const open = root.classList.contains("open");
      closeAll(null);
      if (!open) {
        viewDate = parseDateStr(current);
        renderCal();
        openDropdown(root);
      }
    };

    updateText();

    return {
      getValue: () => current,
      setValue: (v) => { current = v; updateText(); },
      destroy: () => { wrap.remove(); }
    };
  }

  function createTimePicker(container, opts) {
    const { label, value = "10:00", onChange } = opts;
    const wrap = mountField(container, label);
    const root = document.createElement("div");
    root.className = "ui-timepicker ui-dropdown";
    let current = value;

    const slots = [];
    for (let h = 8; h <= 20; h++) {
      slots.push(pad(h) + ":00");
      if (h < 20) slots.push(pad(h) + ":30");
    }

    root.innerHTML = `
      <button type="button" class="ui-trigger">
        <span class="ui-icon-clock"></span>
        <span class="ui-trigger-text"></span>
        <span class="ui-chevron"></span>
      </button>
      <div class="ui-menu ui-time-menu"></div>`;
    wrap.appendChild(root);

    const trigger = root.querySelector(".ui-trigger");
    const textEl = root.querySelector(".ui-trigger-text");
    const menu = root.querySelector(".ui-time-menu");

    function updateText() { textEl.textContent = current; }

    function renderMenu() {
      menu.innerHTML = `<div class="ui-time-grid">${slots.map(t => `
        <button type="button" class="ui-time-slot ${t === current ? "active" : ""}" data-time="${t}">${t}</button>
      `).join("")}</div>`;
      menu.querySelectorAll(".ui-time-slot").forEach(btn => {
        btn.onclick = (e) => {
          e.stopPropagation();
          current = btn.dataset.time;
          updateText();
          closeDropdown(root);
          onChange && onChange(current);
        };
      });
    }

    trigger.onclick = (e) => {
      e.stopPropagation();
      const open = root.classList.contains("open");
      closeAll(null);
      if (!open) {
        renderMenu();
        openDropdown(root);
      }
    };

    updateText();

    return {
      getValue: () => current,
      setValue: (v) => { current = v; updateText(); },
      destroy: () => { wrap.remove(); }
    };
  }

  function createSearchSelect(container, opts) {
    const { label, options = [], value = "", placeholder = "Начните вводить…", onChange } = opts;
    const wrap = mountField(container, label);
    const root = document.createElement("div");
    root.className = "ui-search-select ui-dropdown";
    root.innerHTML = `
      <div class="ui-search-trigger">
        <input type="text" class="ui-search-input" autocomplete="off" placeholder="${placeholder}">
        <span class="ui-chevron"></span>
      </div>
      <div class="ui-menu ui-search-menu"></div>`;
    wrap.appendChild(root);

    const input = root.querySelector(".ui-search-input");
    const menu = root.querySelector(".ui-menu");
    let current = value;

    function labelOf(v) {
      return options.find(o => String(o.value) === String(v))?.label || "";
    }

    function renderMenu() {
      const q = input.value.trim().toLowerCase();
      const items = options.filter(o => {
        if (!q) return true;
        const label = String(o.label || "").toLowerCase();
        const value = String(o.value || "").toLowerCase();
        return label.includes(q) || value.includes(q);
      });
      menu.innerHTML = items.length
        ? items.map(o => `
          <button type="button" class="ui-option ${String(o.value) === String(current) ? "active" : ""}" data-value="${o.value}">
            ${o.label}
          </button>`).join("")
        : `<div class="ui-search-empty">Ничего не найдено</div>`;
      menu.querySelectorAll(".ui-option").forEach(btn => {
        btn.onclick = (e) => {
          e.stopPropagation();
          current = btn.dataset.value;
          input.value = labelOf(current);
          closeDropdown(root);
          onChange && onChange(current);
        };
      });
    }

    function openMenu() {
      closeAll(root);
      renderMenu();
      openDropdown(root);
    }

    input.value = labelOf(current);
    input.onfocus = () => { input.select(); openMenu(); };
    input.oninput = () => openMenu();
    input.onclick = (e) => { e.stopPropagation(); openMenu(); };
    input.onblur = () => {
      setTimeout(() => {
        if (root.classList.contains("open")) return;
        const q = input.value.trim();
        if (!q) {
          if (current) {
            current = "";
            onChange && onChange("");
          }
          return;
        }
        const byValue = options.find(o => String(o.value).toLowerCase() === q.toLowerCase());
        if (byValue) {
          current = byValue.value;
          input.value = byValue.label;
          onChange && onChange(current);
          return;
        }
        const byLabel = options.find(o => o.label.toLowerCase() === q.toLowerCase());
        if (byLabel) {
          current = byLabel.value;
          input.value = byLabel.label;
          onChange && onChange(current);
          return;
        }
        const partial = options.filter(o => o.label.toLowerCase().includes(q.toLowerCase()));
        if (partial.length === 1) {
          current = partial[0].value;
          input.value = partial[0].label;
          onChange && onChange(current);
        }
      }, 150);
    };
    root.querySelector(".ui-search-trigger").onclick = (e) => {
      e.stopPropagation();
      if (root.classList.contains("open")) closeDropdown(root);
      else openMenu();
    };

    return {
      getValue: () => current,
      setValue: (v) => { current = v; input.value = labelOf(v); },
      setOptions: (arr) => { options.length = 0; arr.forEach(o => options.push(o)); input.value = labelOf(current); },
      destroy: () => { wrap.remove(); }
    };
  }

  global.UI = { createSelect, createSearchSelect, createDatePicker, createTimePicker, toDateStr, parseDateStr };
})(window);
