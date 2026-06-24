(function (global) {
  "use strict";

  var API_PREFIX = "/api/v1";

  function getToken() {
    return global.MaxRassAuth && global.MaxRassAuth.getAccessToken
      ? global.MaxRassAuth.getAccessToken()
      : null;
  }

  function formatApiError(payload, statusText) {
    var detail = (payload && payload.detail) || statusText || "Ошибка запроса";
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map(function (item) {
        var loc = (item.loc || []).slice(1).join(".");
        var msg = item.msg || "";
        if (item.type === "too_short" && loc === "items") {
          return "Укажите хотя бы одного пользователя с фамилией и именем";
        }
        return (loc ? loc + ": " : "") + msg;
      }).join("; ");
    }
    if (typeof detail === "object") return JSON.stringify(detail);
    return String(detail);
  }

  async function request(method, path, body) {
    var token = getToken();
    if (!token) {
      global.location.replace("/");
      throw new Error("Нет токена авторизации");
    }

    var options = {
      method: method,
      headers: {
        Authorization: "Bearer " + token,
        Accept: "application/json",
      },
    };

    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }

    var response = await fetch(API_PREFIX + path, options);
    var payload = null;
    try {
      payload = await response.json();
    } catch (_error) {
      payload = null;
    }

    if (!response.ok) {
      var detail = formatApiError(payload, response.statusText);
      if (response.status === 401 && global.MaxRassAuth && global.MaxRassAuth.redirectToLogin) {
        global.MaxRassAuth.redirectToLogin(global.location.pathname);
      }
      throw new Error(detail);
    }

    return payload;
  }

  function get(path) {
    return request("GET", path);
  }

  function post(path, body) {
    return request("POST", path, body);
  }

  function patch(path, body) {
    return request("PATCH", path, body);
  }

  function put(path, body) {
    return request("PUT", path, body);
  }

  function del(path) {
    return request("DELETE", path);
  }

  function fmtDate(value) {
    if (!value) return "—";
    return new Date(value).toLocaleString("ru-RU");
  }

  function fmtName(row) {
    return [row.last_name, row.first_name, row.middle_name].filter(Boolean).join(" ");
  }

  function showToast(elementId, message, isError) {
    var el = document.getElementById(elementId);
    if (!el) return;
    el.textContent = message;
    el.className = "toast show" + (isError ? " error" : "");
    clearTimeout(el._timer);
    el._timer = setTimeout(function () {
      el.className = "toast";
    }, 4000);
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  global.MaxRassApi = {
    get: get,
    post: post,
    patch: patch,
    put: put,
    del: del,
    fmtDate: fmtDate,
    fmtName: fmtName,
    showToast: showToast,
    escapeHtml: escapeHtml,
    seedDemo: function () {
      return fetch(API_PREFIX.replace("/v1", "") + "/v1/db/seed-demo", { method: "POST" })
        .then(function (r) { return r.json(); });
    },
  };
})(window);
