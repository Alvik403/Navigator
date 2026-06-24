(function (global) {
  "use strict";

  var OIDC_STORAGE_PREFIX = "oidc.user:";
  var APP_AUTH_KEY = "max-rass.app.auth";

  function findOidcUserRaw() {
    var best = null;
    for (var index = 0; index < sessionStorage.length; index += 1) {
      var key = sessionStorage.key(index);
      if (!key || key.indexOf(OIDC_STORAGE_PREFIX) !== 0) {
        continue;
      }
      try {
        var parsed = JSON.parse(sessionStorage.getItem(key));
        if (parsed && parsed.access_token) {
          best = parsed;
        }
      } catch (_error) {
        return null;
      }
    }
    return best;
  }

  function clearOidcStorage() {
    var keys = [];
    for (var index = 0; index < sessionStorage.length; index += 1) {
      var key = sessionStorage.key(index);
      if (key && key.indexOf("oidc.") === 0) {
        keys.push(key);
      }
    }
    keys.forEach(function (key) {
      sessionStorage.removeItem(key);
    });
  }

  function decodeTokenRoles(token) {
    if (!token) return [];
    try {
      var segment = token.split(".")[1];
      var base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
      var padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
      var payload = JSON.parse(atob(padded));
      var realm = (payload.realm_access && payload.realm_access.roles) || [];
      var direct = payload.roles || [];
      return realm.concat(direct);
    } catch (_error) {
      return [];
    }
  }

  function getRoles(user) {
    if (!user) return [];
    var profile = user.profile || {};
    var profileRoles = (profile.realm_access && profile.realm_access.roles) || profile.roles || [];
    var tokenRoles = decodeTokenRoles(user.access_token).concat(decodeTokenRoles(user.id_token));
    var merged = profileRoles.concat(tokenRoles);
    return merged.filter(function (role, index) {
      return merged.indexOf(role) === index;
    });
  }

  function getSystemAuth() {
    try {
      var raw = sessionStorage.getItem(APP_AUTH_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_error) {
      sessionStorage.removeItem(APP_AUTH_KEY);
      return null;
    }
  }

  function getAppRole() {
    var auth = getSystemAuth();
    return auth && (auth.app_role_code || (auth.profile && auth.profile.role_code)) || null;
  }

  function displayName(profile) {
    if (profile.name) return profile.name;
    var given = profile.given_name || "";
    var family = profile.family_name || "";
    var full = (given + " " + family).trim();
    if (full) return full;
    return profile.preferred_username || profile.email || "Пользователь";
  }

  function initials(name) {
    return name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(function (part) { return part[0]; })
      .join("")
      .toUpperCase() || "?";
  }

  function requireSession(redirectPath) {
    var user = findOidcUserRaw();
    if (!user || !user.access_token) {
      clearOidcStorage();
      global.location.replace(redirectPath || "/");
      return null;
    }
    if (user.expires_at && user.expires_at * 1000 < Date.now()) {
      clearOidcStorage();
      global.location.replace(redirectPath || "/");
      return null;
    }
    return user;
  }

  function requireRoles(allowedRoles, redirectPath) {
    var user = requireSession(redirectPath);
    if (!user) return null;
    var roles = getRoles(user);
    var ok = allowedRoles.some(function (role) {
      return roles.indexOf(role) !== -1;
    });
    if (!ok) {
      global.location.replace(redirectPath || "/");
      return null;
    }
    return user;
  }

  function requireSystemRoles(allowedRoles, redirectPath) {
    var user = requireSession(redirectPath);
    if (!user) return null;

    var appRole = getAppRole();
    var keycloakRoles = getRoles(user);
    var ok = allowedRoles.indexOf(appRole) !== -1;

    if (!ok && appRole !== "admin") {
      ok = allowedRoles.some(function (role) {
        if (role === "hr") return keycloakRoles.indexOf("hr_manager") !== -1;
        return false;
      });
    }

    if (!ok) {
      global.location.replace(redirectPath || "/");
      return null;
    }
    return user;
  }

  function getAccessToken() {
    var user = findOidcUserRaw();
    return user && user.access_token ? user.access_token : null;
  }

  function applyUserToHeader() {
    var user = findOidcUserRaw();
    if (!user) return;
    var profile = user.profile || {};
    var name = displayName(profile);
    var abbr = initials(name);

    ["userAvatar", "hrAvatar", "teacherAvatar", "testAvatar", "adminAvatar"].forEach(function (id) {
      var element = document.getElementById(id);
      if (element) element.textContent = abbr;
    });

    ["userName", "hrName", "teacherName", "testUserName", "adminName"].forEach(function (id) {
      var element = document.getElementById(id);
      if (element) element.textContent = name;
    });
  }

  function redirectToLogin(returnPath) {
    clearOidcStorage();
    sessionStorage.setItem("max-rass.auth.return", returnPath || global.location.pathname);
    global.location.replace("/");
  }

  function isAuthErrorMessage(message) {
    var text = String(message || "").toLowerCase();
    return text.indexOf("токен") !== -1 || text.indexOf("авториз") !== -1 || text.indexOf("401") !== -1;
  }

  global.MaxRassAuth = {
    requireSession: requireSession,
    requireRoles: requireRoles,
    requireSystemRoles: requireSystemRoles,
    getRoles: getRoles,
    getAppRole: getAppRole,
    getAccessToken: getAccessToken,
    applyUserToHeader: applyUserToHeader,
    getUser: findOidcUserRaw,
    clearOidcStorage: clearOidcStorage,
    redirectToLogin: redirectToLogin,
    isAuthErrorMessage: isAuthErrorMessage,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyUserToHeader);
  } else {
    applyUserToHeader();
  }
})(window);
