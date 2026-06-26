import { AUTH_RETURN_KEY, PORTALS, type Portal } from "./config";
import {
  AuthError,
  changePassword,
  clearLocalAuth,
  ensureAuthenticated,
  getUser,
  handleCallback,
  loginWithPassword,
  performLogout,
  resolveDashboard,
  resolveDashboardForAuthenticatedUser,
  userRequiresPasswordChange,
  waitForKeycloakReady,
} from "./auth";
import {
  completeMaxLogin,
  clearMaxSessionId,
  exchangeMaxSession,
  getMaxSessionId,
  getMaxStatus,
  openMaxBotInNewTab,
  startMaxLogin,
  startMaxPasswordReset,
  type MaxStatusResponse,
} from "./max-auth";

type RouteHandler = () => Promise<void> | void;

let maxPollTimer: number | null = null;
let maxCountdownTimer: number | null = null;
let maxPollCleanup: (() => void) | null = null;
let maxLoginRenderToken = 0;
const MAX_BOT_URL_KEY = "max-rass.max.bot-url";
const MAX_FLOW_MODE_KEY = "max-rass.max.flow-mode";
const RESET_USERNAME_KEY = "max-rass.reset.username";
const DEFAULT_MAX_POLL_MS = 2000;

type MaxFlowMode = "login" | "reset";

function getMaxFlowMode(): MaxFlowMode {
  return new URLSearchParams(window.location.search).get("mode") === "reset" ? "reset" : "login";
}

const routes: Record<string, RouteHandler> = {
  "/": renderLoginPage,
  "/login": () => navigate("/", true),
  "/login/hr": () => navigate("/", true),
  "/max": renderMaxLogin,
  "/change-password": renderChangePasswordPage,
  "/callback": renderCallback,
  "/hr": () => renderProtectedPortal("hr"),
  "/admin": () => renderProtectedPortal("admin"),
  "/db-test": renderDbTest,
  "/logout": renderLogout,
};

export function startRouter(): void {
  window.addEventListener("popstate", () => {
    void navigate(window.location.pathname, false);
  });
  void navigate(window.location.pathname, false);
}

export function navigate(path: string, push = true): void {
  const normalized = normalizePath(path);
  if (push && window.location.pathname !== normalized) {
    history.pushState({}, "", normalized);
  }
  void runRoute(normalized);
}

function normalizePath(path: string): string {
  const url = new URL(path, window.location.origin);
  return url.pathname.replace(/\/+$/, "") || "/";
}

const DASHBOARD_STATIC_PATHS = new Set([
  "/hr-dashboard.html",
  "/admin-dashboard.html",
]);

async function runRoute(path: string): Promise<void> {
  if (DASHBOARD_STATIC_PATHS.has(path)) {
    renderStaticDashboardHint(path);
    return;
  }
  const handler = routes[path];
  if (!handler) {
    renderNotFound();
    return;
  }
  await handler();
}

function renderStaticDashboardHint(path: string): void {
  const app = getApp();
  app.innerHTML = `
    <main class="shell">
      <section class="card">
        <h1>Загрузка панели…</h1>
        <p>Если страница не открылась, пересоберите frontend и перезапустите контейнер web:</p>
        <pre style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:8px">cd app/web && npm run build
cd .. && docker compose up -d --build web max-auth</pre>
        <div class="actions" style="margin-top:16px">
          <a class="btn btn-primary" href="${escapeHtml(path)}">Открыть ${escapeHtml(path)}</a>
          <a class="btn btn-secondary" href="/">На главную</a>
        </div>
      </section>
    </main>
  `;
  window.setTimeout(() => {
    window.location.replace(path);
  }, 100);
}

function renderNotFound(): void {
  const app = getApp();
  app.innerHTML = `
    <main class="shell">
      <section class="card">
        <h1>Страница не найдена</h1>
        <p>Маршрут <code>${escapeHtml(window.location.pathname)}</code> не существует.</p>
        <div class="actions">
          <a class="btn btn-primary" href="/">На главную</a>
        </div>
      </section>
    </main>
  `;
}

async function renderLoginPage(): Promise<void> {
  const user = await getUser().catch(() => null);

  if (user && !user.expired) {
    if (await userRequiresPasswordChange(user.access_token)) {
      window.location.replace("/change-password");
      return;
    }
    const dashboard = await resolveDashboardForAuthenticatedUser(user);
    if (dashboard) {
      window.location.replace(dashboard);
      return;
    }
    renderAuthResult({
      variant: "error",
      title: "Нет доступа к системе",
      message: "У вашей учётной записи нет системной роли admin или hr.",
      hint: "Обратитесь к системному администратору.",
    });
    return;
  }

  await renderLoginFrame();
}

type IconHost = Window & { ICONS?: { enhance: (root?: ParentNode) => void } };

function ensureAuthPageAssets(): void {
  if (!document.getElementById("theme-css")) {
    const link = document.createElement("link");
    link.id = "theme-css";
    link.rel = "stylesheet";
    link.href = "/theme.css";
    document.head.appendChild(link);
  }
  if (!document.getElementById("auth-css")) {
    const link = document.createElement("link");
    link.id = "auth-css";
    link.rel = "stylesheet";
    link.href = "/auth.css";
    document.head.appendChild(link);
  }
  if (!document.getElementById("icons-css")) {
    const link = document.createElement("link");
    link.id = "icons-css";
    link.rel = "stylesheet";
    link.href = "/icons.css";
    document.head.appendChild(link);
  }
}

function applyAuthIcons(root: ParentNode): void {
  const host = window as IconHost;
  if (host.ICONS) {
    host.ICONS.enhance(root);
    return;
  }
  if (document.getElementById("icons-js")) {
    return;
  }
  const script = document.createElement("script");
  script.id = "icons-js";
  script.src = "/icons.js";
  script.onload = () => host.ICONS?.enhance(root);
  document.head.appendChild(script);
}

async function renderLoginFrame(errorMessage = ""): Promise<void> {
  ensureAuthPageAssets();

  const resetUsername = sessionStorage.getItem(RESET_USERNAME_KEY) ?? "";
  const app = getApp();
  app.innerHTML = `
    <main class="shell">
      <section class="auth-card auth-panel active" aria-label="Вход в систему">
        <div class="card-header">
          <h2>Вход в систему</h2>
          <p>Корпоративная учётная запись</p>
        </div>

        <form id="passwordLoginForm" novalidate>
          <div class="field">
            <label for="loginUsername">Логин или email</label>
            <input id="loginUsername" name="username" type="text" autocomplete="username" placeholder="ivanov@company.ru" value="${escapeHtml(resetUsername)}" required>
          </div>

          <div class="field">
            <label for="loginPassword">Пароль</label>
            <input id="loginPassword" name="password" type="password" autocomplete="current-password" placeholder="••••••••" required>
          </div>

          <p class="error${errorMessage ? " visible" : ""}" id="formError" role="alert">${escapeHtml(errorMessage)}</p>

          <div class="row">
            <label><input type="checkbox" id="rememberMe"> Запомнить меня</label>
            <a href="/max?mode=reset" id="forgotLink">Забыли пароль?</a>
          </div>

          <button class="auth-btn auth-btn-primary" type="submit" id="passwordLoginBtn" data-icon="login">Войти</button>
        </form>

        <div class="divider">или</div>

        <button class="auth-btn auth-btn-max" type="button" id="maxLoginBtn" data-icon="phone">Войти через MAX</button>
        <p class="login-status" id="loginStatus"></p>
      </section>
    </main>
  `;

  applyAuthIcons(app);

  const form = document.getElementById("passwordLoginForm") as HTMLFormElement | null;
  const usernameInput = document.getElementById("loginUsername") as HTMLInputElement | null;
  const passwordInput = document.getElementById("loginPassword") as HTMLInputElement | null;
  const submitBtn = document.getElementById("passwordLoginBtn") as HTMLButtonElement | null;
  const formError = document.getElementById("formError");
  const statusEl = document.getElementById("loginStatus");

  document.getElementById("maxLoginBtn")?.addEventListener("click", () => {
    navigate("/max", true);
  });

  document.getElementById("forgotLink")?.addEventListener("click", (event) => {
    event.preventDefault();
    history.pushState({}, "", "/max?mode=reset");
    navigate("/max", false);
  });

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const username = usernameInput?.value.trim() ?? "";
    const password = passwordInput?.value ?? "";

    usernameInput?.classList.remove("invalid");
    passwordInput?.classList.remove("invalid");
    formError?.classList.remove("visible");
    if (formError) formError.textContent = "";

    if (!username || !password) {
      if (formError) {
        formError.textContent = "Введите логин и пароль";
        formError.classList.add("visible");
      }
      if (!username) usernameInput?.classList.add("invalid");
      if (!password) passwordInput?.classList.add("invalid");
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Проверка…";
    }
    if (statusEl) statusEl.textContent = "Проверяем логин и пароль…";

    try {
      await waitForKeycloakReady();
      const { portal } = await loginWithPassword(username, password);
      if (await userRequiresPasswordChange()) {
        sessionStorage.removeItem(RESET_USERNAME_KEY);
        if (statusEl) statusEl.textContent = "Вход выполнен. Перенаправляем на смену пароля…";
        window.location.replace("/change-password");
        return;
      }
      sessionStorage.removeItem(RESET_USERNAME_KEY);
      if (statusEl) statusEl.textContent = `Вход выполнен. Открываем ${PORTALS[portal].title}…`;
      const returnPath = sessionStorage.getItem(AUTH_RETURN_KEY);
      sessionStorage.removeItem(AUTH_RETURN_KEY);
      const target =
        returnPath && returnPath !== "/callback" && returnPath !== "/" && returnPath !== "/login"
          ? returnPath
          : resolveDashboard(portal);
      window.location.replace(target);
    } catch (error) {
      clearLocalAuth();
      const message =
        error instanceof AuthError
          ? `${error.message}. ${error.hint}`
          : error instanceof Error
            ? error.message
            : "Не удалось выполнить вход.";
      await renderLoginFrame(message);
    }
  });
}

function stopMaxTimers(): void {
  if (maxPollTimer !== null) {
    window.clearInterval(maxPollTimer);
    maxPollTimer = null;
  }
  if (maxCountdownTimer !== null) {
    window.clearInterval(maxCountdownTimer);
    maxCountdownTimer = null;
  }
  maxPollCleanup?.();
  maxPollCleanup = null;
}

async function renderMaxLogin(): Promise<void> {
  const renderToken = ++maxLoginRenderToken;
  stopMaxTimers();
  const app = getApp();
  const isStale = () => renderToken !== maxLoginRenderToken;
  const flowMode = getMaxFlowMode();
  sessionStorage.setItem(MAX_FLOW_MODE_KEY, flowMode);
  const isResetFlow = flowMode === "reset";

  const user = await getUser();
  if (user && !user.expired && !isResetFlow) {
      const dashboard = await resolveDashboardForAuthenticatedUser(user);
    if (dashboard) {
      window.location.replace(dashboard);
      return;
    }
  }

  const existingSessionId = getMaxSessionId();
  if (existingSessionId) {
    try {
      const existingStatus = await getMaxStatus(existingSessionId);
      if (isStale()) return;
      if (existingStatus.status === "confirmed" && !isResetFlow) {
        await finishMaxLogin(existingSessionId);
        return;
      }
      if (existingStatus.status === "password_reset") {
        finishMaxPasswordReset(existingStatus);
        return;
      }
      if (existingStatus.status === "pending") {
        const botUrl = sessionStorage.getItem(MAX_BOT_URL_KEY) ?? undefined;
        const storedMode = sessionStorage.getItem(MAX_FLOW_MODE_KEY) as MaxFlowMode | null;
        mountMaxWaitingUi(
          existingSessionId,
          botUrl,
          existingStatus.expires_at,
          DEFAULT_MAX_POLL_MS,
          storedMode === "reset" ? "reset" : flowMode,
        );
        return;
      }
    } catch {
      sessionStorage.removeItem(MAX_BOT_URL_KEY);
    }
  }

  try {
    const session = isResetFlow ? await startMaxPasswordReset() : await startMaxLogin();
    if (isStale()) return;
    sessionStorage.setItem(MAX_BOT_URL_KEY, session.bot_url);
    mountMaxWaitingUi(
      session.session_id,
      session.bot_url,
      session.expires_at,
      session.poll_interval_ms || DEFAULT_MAX_POLL_MS,
      flowMode,
    );
    openMaxBotInNewTab(session.bot_url);
  } catch (error) {
    if (isStale()) return;
    app.innerHTML = `
      <main class="shell">
        <section class="card max-card">
          <h2>${isResetFlow ? "Восстановление пароля через MAX" : "Вход через MAX"}</h2>
          <p class="status">${escapeHtml(error instanceof Error ? error.message : "Не удалось начать операцию")}</p>
          <div class="actions">
            <button class="btn btn-primary" type="button" id="maxRetryBtn">Повторить</button>
          </div>
        </section>
      </main>
    `;
    document.getElementById("maxRetryBtn")?.addEventListener("click", () => {
      void renderMaxLogin();
    });
  }
}

function mountMaxWaitingUi(
  sessionId: string,
  botUrl: string | undefined,
  expiresAt: number,
  pollIntervalMs: number,
  flowMode: MaxFlowMode,
): void {
  const isResetFlow = flowMode === "reset";
  const app = getApp();
  app.innerHTML = `
    <main class="shell">
      <section class="card max-card" aria-label="${isResetFlow ? "Восстановление пароля через MAX" : "Подтверждение входа через MAX"}">
        <div class="max-wait">
          <div class="spinner" aria-hidden="true"></div>
          <div class="max-icon">MAX</div>
          <h2>${isResetFlow ? "Восстановление пароля" : "Подтвердите вход"}</h2>
          <p id="maxMessage">${
            isResetFlow
              ? "Откройте бота в новой вкладке, подтвердите восстановление и вернитесь на эту страницу."
              : "Откройте бота в новой вкладке, подтвердите вход и вернитесь на эту страницу."
          }</p>
          <span class="timer" id="maxTimer">Осталось 5:00</span>
          <div class="max-demo-actions">
            ${botUrl ? `<a class="btn btn-max" href="${escapeHtml(botUrl)}" target="_blank" rel="noopener">Открыть бота в MAX</a>` : ""}
          </div>
          <button class="back-link" type="button" id="maxBackBtn">← Вернуться к входу</button>
          <p class="status" id="maxStatus"></p>
        </div>
      </section>
    </main>
  `;

  const timerEl = document.getElementById("maxTimer");
  const statusEl = document.getElementById("maxStatus");
  const backBtn = document.getElementById("maxBackBtn");

  backBtn?.addEventListener("click", () => {
    stopMaxTimers();
    sessionStorage.removeItem(MAX_BOT_URL_KEY);
    sessionStorage.removeItem(MAX_FLOW_MODE_KEY);
    navigate("/", true);
  });

  let secondsLeft = Math.max(0, expiresAt - Math.floor(Date.now() / 1000));
  const renderCountdown = () => {
    if (!timerEl) return;
    const minutes = Math.floor(secondsLeft / 60);
    const seconds = String(secondsLeft % 60).padStart(2, "0");
    timerEl.textContent = secondsLeft > 0 ? `Осталось ${minutes}:${seconds}` : "Время истекло";
  };

  renderCountdown();
  maxCountdownTimer = window.setInterval(() => {
    secondsLeft -= 1;
    renderCountdown();
    if (secondsLeft <= 0 && maxCountdownTimer !== null) {
      window.clearInterval(maxCountdownTimer);
      maxCountdownTimer = null;
    }
  }, 1000);

  const runPoll = () => {
    void pollMaxStatus(sessionId, statusEl);
  };

  runPoll();
  maxPollTimer = window.setInterval(runPoll, pollIntervalMs);

  const onVisible = () => {
    if (!document.hidden) {
      runPoll();
    }
  };
  const onFocus = () => {
    runPoll();
  };
  document.addEventListener("visibilitychange", onVisible);
  window.addEventListener("focus", onFocus);
  maxPollCleanup = () => {
    document.removeEventListener("visibilitychange", onVisible);
    window.removeEventListener("focus", onFocus);
  };
}

function showMaxWaitingState(message: string, hideActions = false): void {
  const messageEl = document.getElementById("maxMessage");
  const timerEl = document.getElementById("maxTimer");
  const spinner = document.querySelector(".max-wait .spinner");
  const actionsEl = document.querySelector(".max-demo-actions");
  const titleEl = document.querySelector(".max-wait h2");

  if (messageEl) messageEl.textContent = message;
  if (timerEl) timerEl.textContent = "";
  if (titleEl && hideActions) titleEl.textContent = "Завершение входа";
  spinner?.remove();
  if (hideActions) {
    actionsEl?.remove();
  }
}

async function finishMaxLogin(sessionId: string): Promise<void> {
  stopMaxTimers();
  const tokens = await exchangeMaxSession(sessionId);
  const dashboard = await completeMaxLogin(tokens);
  sessionStorage.removeItem(MAX_BOT_URL_KEY);
  sessionStorage.removeItem(MAX_FLOW_MODE_KEY);
  window.location.replace(dashboard);
}

function finishMaxPasswordReset(status: MaxStatusResponse): void {
  stopMaxTimers();
  clearMaxSessionId();
  sessionStorage.removeItem(MAX_BOT_URL_KEY);
  sessionStorage.removeItem(MAX_FLOW_MODE_KEY);

  const username = status.keycloak_username ?? "";
  const tempPassword = status.temp_password ?? "";

  if (username) {
    sessionStorage.setItem(RESET_USERNAME_KEY, username);
  }

  ensureAuthPageAssets();
  const app = getApp();
  app.innerHTML = `
    <main class="shell">
      <section class="auth-card auth-panel active" aria-label="Временный пароль">
        <div class="card-header">
          <h2>Пароль восстановлен</h2>
          <p>${username ? `Аккаунт: ${escapeHtml(username)}` : "Подтверждение в MAX выполнено"}</p>
        </div>

        <p class="reset-success-text">
          Временный пароль сгенерирован. Скопируйте его, войдите на сайт и сразу установите новый пароль.
        </p>

        ${
          tempPassword
            ? `
          <div class="temp-password-box">
            <span class="temp-password-label">Временный пароль</span>
            <div class="temp-password-row">
              <code class="temp-password-value" id="tempPasswordValue">${escapeHtml(tempPassword)}</code>
              <button class="copy-btn" type="button" id="copyTempPasswordBtn">Копировать</button>
            </div>
            <p class="copy-status" id="copyStatus"></p>
          </div>
        `
            : `<div class="alert alert-info">Временный пароль также отправлен в чат MAX.</div>`
        }

        <button class="auth-btn auth-btn-primary" type="button" id="goToLoginBtn" data-icon="login">
          Перейти ко входу
        </button>
      </section>
    </main>
  `;

  applyAuthIcons(app);

  document.getElementById("copyTempPasswordBtn")?.addEventListener("click", async () => {
    const copyStatus = document.getElementById("copyStatus");
    if (!tempPassword) return;
    try {
      await navigator.clipboard.writeText(tempPassword);
      if (copyStatus) copyStatus.textContent = "Пароль скопирован";
    } catch {
      const valueEl = document.getElementById("tempPasswordValue");
      if (valueEl) {
        const range = document.createRange();
        range.selectNodeContents(valueEl);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
      }
      if (copyStatus) copyStatus.textContent = "Выделите пароль и скопируйте вручную (Ctrl+C)";
    }
  });

  document.getElementById("goToLoginBtn")?.addEventListener("click", () => {
    navigate("/", true);
  });
}

async function renderChangePasswordPage(): Promise<void> {
  ensureAuthPageAssets();

  const user = await getUser().catch(() => null);
  if (!user || user.expired) {
    window.location.replace("/");
    return;
  }

  if (!(await userRequiresPasswordChange(user.access_token))) {
    const dashboard = await resolveDashboardForAuthenticatedUser(user);
    window.location.replace(dashboard ?? "/");
    return;
  }

  const app = getApp();
  app.innerHTML = `
    <main class="shell">
      <section class="auth-card auth-panel active" aria-label="Смена пароля">
        <div class="card-header">
          <h2>Установите новый пароль</h2>
          <p>Вы вошли с временным паролем. Задайте постоянный пароль для продолжения работы.</p>
        </div>

        <form id="changePasswordForm" novalidate>
          <div class="field">
            <label for="newPassword">Новый пароль</label>
            <input id="newPassword" name="newPassword" type="password" autocomplete="new-password" minlength="8" required>
          </div>
          <div class="field">
            <label for="confirmPassword">Подтверждение</label>
            <input id="confirmPassword" name="confirmPassword" type="password" autocomplete="new-password" minlength="8" required>
          </div>
          <p class="error" id="changePasswordError" role="alert"></p>
          <button class="auth-btn auth-btn-primary" type="submit" id="changePasswordBtn" data-icon="check">
            Сохранить пароль
          </button>
        </form>
      </section>
    </main>
  `;

  applyAuthIcons(app);

  const form = document.getElementById("changePasswordForm") as HTMLFormElement | null;
  const newPasswordInput = document.getElementById("newPassword") as HTMLInputElement | null;
  const confirmPasswordInput = document.getElementById("confirmPassword") as HTMLInputElement | null;
  const submitBtn = document.getElementById("changePasswordBtn") as HTMLButtonElement | null;
  const errorEl = document.getElementById("changePasswordError");

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const newPassword = newPasswordInput?.value ?? "";
    const confirmation = confirmPasswordInput?.value ?? "";

    if (errorEl) {
      errorEl.textContent = "";
      errorEl.classList.remove("visible");
    }

    if (newPassword.length < 8) {
      if (errorEl) {
        errorEl.textContent = "Пароль должен содержать минимум 8 символов";
        errorEl.classList.add("visible");
      }
      return;
    }

    if (newPassword !== confirmation) {
      if (errorEl) {
        errorEl.textContent = "Пароли не совпадают";
        errorEl.classList.add("visible");
      }
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Сохранение…";
    }

    try {
      await changePassword(newPassword, confirmation);
      sessionStorage.removeItem(RESET_USERNAME_KEY);
      const updatedUser = await getUser();
      const dashboard = updatedUser ? await resolveDashboardForAuthenticatedUser(updatedUser) : null;
      window.location.replace(dashboard ?? "/");
    } catch (error) {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Сохранить пароль";
        applyAuthIcons(app);
      }
      if (errorEl) {
        errorEl.textContent =
          error instanceof AuthError
            ? `${error.message}. ${error.hint}`
            : error instanceof Error
              ? error.message
              : "Не удалось сменить пароль";
        errorEl.classList.add("visible");
      }
    }
  });
}

async function pollMaxStatus(sessionId: string, statusEl: HTMLElement | null): Promise<void> {
  try {
    const status = await getMaxStatus(sessionId);
    if (status.status === "confirmed") {
      stopMaxTimers();
      showMaxWaitingState("Вход подтверждён в MAX. Завершаем авторизацию…", true);
      if (statusEl) statusEl.textContent = "Получаем токен…";
      try {
        await finishMaxLogin(sessionId);
      } catch (error) {
        clearLocalAuth();
        renderAuthError(error);
      }
      return;
    }
    if (status.status === "password_reset") {
      finishMaxPasswordReset(status);
      return;
    }
    if (status.status === "rejected") {
      stopMaxTimers();
      showMaxWaitingState("Вход отклонён в MAX.", true);
      if (statusEl) statusEl.textContent = "Начните вход заново.";
      return;
    }
    if (status.status === "expired") {
      stopMaxTimers();
      showMaxWaitingState("Время подтверждения истекло.", true);
      if (statusEl) statusEl.textContent = "Начните вход заново.";
    }
  } catch (error) {
    if (statusEl) {
      statusEl.textContent = error instanceof Error ? error.message : "Ошибка проверки статуса";
    }
  }
}

async function renderCallback(): Promise<void> {
  if (window.self !== window.top) {
    window.top!.location.replace(window.location.href);
    return;
  }

  renderAuthResult({
    variant: "loading",
    title: "Завершение входа",
    message: "Проверяем учётную запись и перенаправляем в портал…",
  });

  try {
    const { portal, user } = await handleCallback();
    void user;

    renderAuthResult({
      variant: "success",
      title: "Вход выполнен",
      message: `Открываем ${PORTALS[portal].title}…`,
    });

    const returnPath = sessionStorage.getItem(AUTH_RETURN_KEY);
    sessionStorage.removeItem(AUTH_RETURN_KEY);

    const target =
      returnPath && returnPath !== "/callback" && returnPath !== "/" && returnPath !== "/login"
        ? returnPath
        : resolveDashboard(portal);

    window.setTimeout(() => {
      window.location.replace(target);
    }, 400);
  } catch (error) {
    clearLocalAuth();
    renderAuthError(error);
  }
}

function renderAuthError(error: unknown): void {
  if (error instanceof AuthError) {
    renderAuthResult({
      variant: "error",
      title: error.code === "insufficient_roles" ? "Нет доступа к системе" : "Ошибка входа",
      message: error.message,
      hint: error.hint,
    });
    return;
  }

  renderAuthResult({
    variant: "error",
    title: "Ошибка входа",
    message: error instanceof Error ? error.message : "Не удалось завершить авторизацию.",
    hint: "Попробуйте войти снова. Если ошибка повторяется, обратитесь к администратору.",
  });
}

interface AuthResultOptions {
  variant: "loading" | "success" | "error";
  title: string;
  message: string;
  hint?: string;
  showAdminLink?: boolean;
}

function renderAuthResult(options: AuthResultOptions): void {
  const app = getApp();
  const iconMarkup =
    options.variant === "loading"
      ? '<div class="spinner" aria-hidden="true"></div>'
      : `<div class="auth-icon auth-icon-${options.variant}" aria-hidden="true">${options.variant === "success" ? "✓" : "!"}</div>`;

  const hintMarkup = options.hint
    ? `<div class="alert alert-${options.variant === "error" ? "error" : "info"}">${escapeHtml(options.hint)}</div>`
    : "";

  const actionsMarkup =
    options.variant === "error"
      ? `
        <div class="actions">
          <a class="btn btn-primary" href="/">Вернуться ко входу</a>
          ${options.showAdminLink ? `<a class="btn btn-secondary" href="/admin">Админ-панель</a>` : ""}
        </div>
      `
      : "";

  app.innerHTML = `
    <main class="shell">
      <section class="card auth-card" aria-live="polite">
        <div class="auth-result">
          ${iconMarkup}
          <h1>${escapeHtml(options.title)}</h1>
          <p>${escapeHtml(options.message)}</p>
          ${hintMarkup}
          ${actionsMarkup}
        </div>
      </section>
    </main>
  `;
}

interface DbQueryResponse {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  limit: number;
}

const DB_SAMPLE_QUERIES = [
  {
    title: "Профили и роли",
    sql: `SELECT p.user_id, p.last_name, p.first_name, r.code AS role, p.phone, p.id_curator, p.status
FROM app.profiles p
JOIN app.roles r ON r.id = p.role_id
ORDER BY p.last_name`,
  },
  {
    title: "Занятия и участники",
    sql: `SELECT l.id AS lesson_id, g.name AS group_name, l.lesson_type, l.starts_at, p.last_name, am.status AS attendance
FROM app.lessons l
JOIN app.groups g ON g.id = l.group_id
JOIN app.lesson_members lm ON lm.lesson_id = l.id
JOIN app.profiles p ON p.user_id = lm.user_id
LEFT JOIN app.attendance_marks am ON am.user_id = lm.user_id AND am.lesson_id = lm.lesson_id
ORDER BY l.starts_at`,
  },
  {
    title: "Страйки",
    sql: `SELECT s.id, p.last_name, p.first_name, s.reason, s.status, s.strike_number, s.created_at
FROM app.strikes s
JOIN app.profiles p ON p.user_id = s.user_id
ORDER BY s.created_at DESC`,
  },
  {
    title: "Уведомления",
    sql: `SELECT n.kind, n.sent_at, p.last_name, p.first_name, l.starts_at
FROM app.notifications n
JOIN app.profiles p ON p.user_id = n.delivered_to
JOIN app.lessons l ON l.id = n.lesson_id
ORDER BY n.sent_at DESC`,
  },
];

async function renderDbTest(): Promise<void> {
  const app = getApp();
  app.innerHTML = `
    <main class="db-shell">
      <section class="db-header">
        <div>
          <p class="eyebrow">Навигатор · БД</p>
          <h1>Тест запросов к базе данных</h1>
          <p>Страница выполняет только read-only SELECT/WITH-запросы через API <code>/api/v1/db/query</code>.</p>
        </div>
        <div class="db-header-actions">
          <a class="btn btn-secondary" href="/docs/database-test-manual.md" target="_blank" rel="noopener">Мануал</a>
          <button class="btn btn-primary" type="button" id="seedDemoBtn">Заполнить demo</button>
        </div>
      </section>

      <section class="db-grid">
        <article class="db-panel">
          <h2>Быстрые запросы</h2>
          <div class="db-samples">
            ${DB_SAMPLE_QUERIES.map(
              (query, index) => `<button class="db-sample" type="button" data-sample="${index}">${escapeHtml(query.title)}</button>`,
            ).join("")}
          </div>
        </article>

        <article class="db-panel">
          <h2>SQL</h2>
          <textarea id="dbSql" spellcheck="false">${escapeHtml(DB_SAMPLE_QUERIES[0].sql)}</textarea>
          <div class="db-form-row">
            <label>
              Лимит строк
              <input id="dbLimit" type="number" min="1" max="200" value="50">
            </label>
            <button class="btn btn-primary" type="button" id="runDbQueryBtn">Выполнить</button>
          </div>
        </article>
      </section>

      <section class="db-panel">
        <div class="db-result-header">
          <h2>Результат</h2>
          <span id="dbStatus">Готово к запросу</span>
        </div>
        <div id="dbResult" class="db-result muted-box">Нажмите «Выполнить» или выберите быстрый запрос.</div>
      </section>
    </main>
  `;

  const sqlEl = document.getElementById("dbSql") as HTMLTextAreaElement | null;
  const limitEl = document.getElementById("dbLimit") as HTMLInputElement | null;
  const statusEl = document.getElementById("dbStatus");
  const resultEl = document.getElementById("dbResult");

  document.querySelectorAll<HTMLButtonElement>(".db-sample").forEach((button) => {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.sample ?? 0);
      if (sqlEl) sqlEl.value = DB_SAMPLE_QUERIES[index]?.sql ?? DB_SAMPLE_QUERIES[0].sql;
    });
  });

  document.getElementById("seedDemoBtn")?.addEventListener("click", async () => {
    await runDbAction(
      async () => {
        const response = await fetch("/api/v1/db/seed-demo", { method: "POST" });
        if (!response.ok) throw new Error(await readApiError(response));
        return response.json();
      },
      statusEl,
      resultEl,
      "Demo-данные добавлены",
    );
  });

  document.getElementById("runDbQueryBtn")?.addEventListener("click", async () => {
    if (!sqlEl || !limitEl) return;
    await runDbAction(
      async () => {
        const response = await fetch("/api/v1/db/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sql: sqlEl.value,
            limit: Number(limitEl.value || 50),
          }),
        });
        if (!response.ok) throw new Error(await readApiError(response));
        return (await response.json()) as DbQueryResponse;
      },
      statusEl,
      resultEl,
      "Запрос выполнен",
      renderDbQueryResult,
    );
  });
}

async function runDbAction<T>(
  action: () => Promise<T>,
  statusEl: HTMLElement | null,
  resultEl: HTMLElement | null,
  successMessage: string,
  render: (payload: T) => string = (payload) => `<pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`,
): Promise<void> {
  if (statusEl) statusEl.textContent = "Выполняется…";
  if (resultEl) resultEl.innerHTML = '<div class="spinner" aria-hidden="true"></div>';

  try {
    const payload = await action();
    if (statusEl) statusEl.textContent = successMessage;
    if (resultEl) resultEl.innerHTML = render(payload);
  } catch (error) {
    if (statusEl) statusEl.textContent = "Ошибка";
    if (resultEl) {
      resultEl.innerHTML = `<div class="alert alert-error">${escapeHtml(error instanceof Error ? error.message : "Неизвестная ошибка")}</div>`;
    }
  }
}

function renderDbQueryResult(payload: DbQueryResponse): string {
  if (payload.columns.length === 0) {
    return `<div class="muted-box">Запрос выполнен, строк нет.</div>`;
  }

  return `
    <p class="db-meta">Строк: ${payload.row_count}, лимит: ${payload.limit}</p>
    <div class="db-table-wrap">
      <table class="db-table">
        <thead>
          <tr>${payload.columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr>
        </thead>
        <tbody>
          ${payload.rows.map((row) => `
            <tr>
              ${payload.columns.map((column) => `<td>${escapeHtml(formatDbValue(row[column]))}</td>`).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function formatDbValue(value: unknown): string {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

async function readApiError(response: Response): Promise<string> {
  const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
  return payload?.detail ?? `HTTP ${response.status}`;
}

async function renderProtectedPortal(portal: Portal): Promise<void> {
  const app = getApp();
  app.innerHTML = `
    <main class="shell">
      <section class="card">
        <h1>${escapeHtml(PORTALS[portal].title)}</h1>
        <p>Проверка доступа…</p>
        <div class="status" id="status"></div>
      </section>
    </main>
  `;

  try {
    const user = await ensureAuthenticated(portal);
    window.location.replace(resolveDashboard(portal));
    void user;
  } catch (error) {
    if (error instanceof Error && error.message === "login_required") {
      window.location.replace("/");
      return;
    }
    if (error instanceof Error && error.message === "forbidden") {
      window.location.replace("/");
      return;
    }
    renderAuthError(error);
  }
}

async function renderLogout(): Promise<void> {
  renderAuthResult({
    variant: "loading",
    title: "Выход из системы",
    message: "Завершаем сеанс и очищаем токены…",
  });

  clearMaxSessionId();
  sessionStorage.removeItem(MAX_BOT_URL_KEY);
  sessionStorage.removeItem(MAX_FLOW_MODE_KEY);

  try {
    await waitForKeycloakReady();
    await performLogout();
  } catch {
    clearLocalAuth();
    window.location.replace("/");
  }
}

function getApp(): HTMLElement {
  const app = document.getElementById("app");
  if (!app) {
    throw new Error("Root element #app not found");
  }
  return app;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
