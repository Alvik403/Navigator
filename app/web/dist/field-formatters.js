(function (global) {
  "use strict";

  var UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

  function digitsOnly(value) {
    return String(value || "").replace(/\D/g, "");
  }

  function normalizeMaxId(raw) {
    return digitsOnly(raw);
  }

  function validateMaxId(raw) {
    var normalized = normalizeMaxId(raw);
    if (!normalized) {
      return { valid: true, normalized: "", hint: "Необязательно · 6–12 цифр", empty: true };
    }
    var valid = /^\d{6,12}$/.test(normalized);
    return {
      valid: valid,
      normalized: normalized,
      hint: valid ? "Формат ID MAX: " + normalized : "ID MAX: только цифры, 6–12 символов",
      empty: false,
    };
  }

  function normalizePhone(raw) {
    var d = digitsOnly(raw);
    if (!d) return "";
    if (d.length === 11 && (d[0] === "7" || d[0] === "8")) {
      d = d.slice(1);
    }
    if (d.length === 10) {
      return "+7" + d;
    }
    return "";
  }

  function formatPhoneDisplay(normalized) {
    if (!/^\+7\d{10}$/.test(normalized)) return normalized;
    var d = normalized.slice(2);
    return "+7 " + d.slice(0, 3) + " " + d.slice(3, 6) + "-" + d.slice(6, 8) + "-" + d.slice(8, 10);
  }

  function validatePhone(raw) {
    var normalized = normalizePhone(raw);
    if (!String(raw || "").trim()) {
      return { valid: true, normalized: "", hint: "Необязательно · +7 XXX XXX-XX-XX", empty: true };
    }
    var valid = /^\+7\d{10}$/.test(normalized);
    return {
      valid: valid,
      normalized: normalized,
      display: valid ? formatPhoneDisplay(normalized) : String(raw || "").trim(),
      hint: valid ? formatPhoneDisplay(normalized) : "Телефон: +7 и 10 цифр (8…, 7…, +7…)",
      empty: false,
    };
  }

  function applyFieldState(input, result, validClass, invalidClass) {
    input.classList.remove("field-valid", "field-invalid");
    if (result.empty) return;
    input.classList.add(result.valid ? validClass || "field-valid" : invalidClass || "field-invalid");
  }

  function setHintText(hintEl, text, stateClass) {
    if (!hintEl) return;
    if (!text) {
      hintEl.textContent = "";
      hintEl.style.display = "none";
      hintEl.className = "field-hint-msg";
      return;
    }
    hintEl.style.display = "";
    hintEl.textContent = text;
    hintEl.className = "field-hint-msg" + (stateClass ? " " + stateClass : "");
  }

  function parseFioParts(fio) {
    var parts = String(fio || "").trim().split(/\s+/).filter(Boolean);
    if (parts.length >= 3) {
      return { last_name: parts[0], first_name: parts[1], middle_name: parts.slice(2).join(" ") };
    }
    if (parts.length === 2) {
      return { last_name: parts[1], first_name: parts[0], middle_name: "" };
    }
    if (parts.length === 1) {
      return { last_name: parts[0], first_name: "", middle_name: "" };
    }
    return { last_name: "", first_name: "", middle_name: "" };
  }

  function shortUuid(id) {
    var s = String(id || "");
    return s.length > 13 ? s.slice(0, 8) + "…" : s;
  }

  function createCuratorCombo(container, opts) {
    if (!container || !global.UI || !global.UI.createSearchSelect) {
      return { getValue: function () { return ""; }, destroy: function () {} };
    }
    var curators = opts.curators || [];
    var options = [{ value: "", label: "— не назначен —" }].concat(
      curators.map(function (c) {
        var id = String(c.id);
        return { value: id, label: (c.name || "—") + " · " + shortUuid(id) };
      })
    );
    return global.UI.createSearchSelect(container, {
      options: options,
      value: opts.value || "",
      placeholder: "ФИО или UUID куратора…",
      onChange: opts.onChange,
    });
  }

  function ensureHint(input, key) {
    var id = input.id || key;
    var hintId = (id ? id + "-hint" : key + "-hint");
    var el = document.getElementById(hintId);
    if (!el) {
      el = document.createElement("div");
      el.id = hintId;
      el.className = "field-hint-msg";
      input.insertAdjacentElement("afterend", el);
    }
    return el;
  }

  function attachMaxIdInput(input, opts) {
    if (!input) return { getNormalized: function () { return ""; } };
    input.classList.add("field-max-id");
    input.setAttribute("inputmode", "numeric");
    input.setAttribute("autocomplete", "off");
    input.placeholder = input.placeholder || "123456789";

    function refresh(fromPaste) {
      var result = validateMaxId(input.value);
      if (result.normalized !== digitsOnly(input.value)) {
        input.value = result.normalized;
      }
      applyFieldState(input, result);
      setHintText(
        ensureHint(input, "max"),
        result.empty ? "" : result.hint,
        result.empty ? "" : result.valid ? "valid" : "invalid"
      );
      if (opts && opts.onChange) opts.onChange(result.normalized, result);
      return result;
    }

    input.addEventListener("input", function () { refresh(false); });
    input.addEventListener("paste", function (e) {
      e.preventDefault();
      input.value = normalizeMaxId(e.clipboardData.getData("text"));
      refresh(true);
    });
    refresh(false);

    return {
      getNormalized: function () {
        var r = validateMaxId(input.value);
        return r.valid || r.empty ? r.normalized : null;
      },
      refresh: refresh,
    };
  }

  function attachPhoneInput(input, opts) {
    if (!input) return { getNormalized: function () { return ""; } };
    input.classList.add("field-phone");
    input.setAttribute("inputmode", "tel");
    input.setAttribute("autocomplete", "tel");
    input.placeholder = input.placeholder || "+7 900 123-45-67";

    function refresh(fromPaste) {
      var result = validatePhone(input.value);
      if (result.valid && result.normalized) {
        input.value = result.display;
      } else if (!result.empty && !result.valid && fromPaste) {
        input.value = normalizePhone(input.value) || input.value;
        result = validatePhone(input.value);
        if (result.valid) input.value = result.display;
      }
      applyFieldState(input, result);
      setHintText(
        ensureHint(input, "phone"),
        result.empty ? "" : result.hint,
        result.empty ? "" : result.valid ? "valid" : "invalid"
      );
      if (opts && opts.onChange) opts.onChange(result.normalized, result);
      return result;
    }

    input.addEventListener("input", function () { refresh(false); });
    input.addEventListener("paste", function (e) {
      e.preventDefault();
      var pasted = e.clipboardData.getData("text");
      var norm = normalizePhone(pasted);
      input.value = norm ? formatPhoneDisplay(norm) : pasted;
      refresh(true);
    });
    input.addEventListener("blur", function () {
      var result = validatePhone(input.value);
      if (result.valid && result.normalized) {
        input.value = result.display;
      }
    });
    refresh(false);

    return {
      getNormalized: function () {
        var r = validatePhone(input.value);
        return r.valid || r.empty ? r.normalized : null;
      },
      refresh: refresh,
    };
  }

  function isUuid(value) {
    return UUID_RE.test(String(value || "").trim());
  }

  function normalizeRows(rows) {
    return (rows || []).map(function (row) {
      var next = Object.assign({}, row);
      if (next.id_max != null && next.id_max !== "") {
        next.id_max = normalizeMaxId(next.id_max);
      }
      if (next.phone != null && next.phone !== "") {
        next.phone = normalizePhone(next.phone) || next.phone;
      }
      if (next.id_curator != null && next.id_curator !== "") {
        var c = String(next.id_curator).trim();
        next.id_curator = isUuid(c) ? c : next.id_curator;
      }
      return next;
    });
  }

  global.HrFields = {
    normalizeMaxId: normalizeMaxId,
    normalizePhone: normalizePhone,
    validateMaxId: validateMaxId,
    validatePhone: validatePhone,
    formatPhoneDisplay: formatPhoneDisplay,
    attachMaxIdInput: attachMaxIdInput,
    attachPhoneInput: attachPhoneInput,
    isUuid: isUuid,
    normalizeRows: normalizeRows,
    parseFioParts: parseFioParts,
    createCuratorCombo: createCuratorCombo,
  };
})(window);
