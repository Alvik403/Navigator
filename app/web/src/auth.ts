import {
  OidcClient,
  User,
  UserManager,
  WebStorageStateStore,
  type User as OidcUser,
} from "oidc-client-ts";
import {
  AUTH_RETURN_KEY,
  OIDC_AUTHORITY,
  OIDC_CLIENT_ID,
  OIDC_POST_LOGOUT_URI,
  OIDC_REDIRECT_URI,
  PORTALS,
  resolvePortalFromAppRole,
  resolvePortalFromRoles,
  type Portal,
} from "./config";

const KEYCLOAK_READY_URL = `${OIDC_AUTHORITY}/.well-known/openid-configuration`;
const APP_AUTH_KEY = "max-rass.app.auth";

let userManager: UserManager | null = null;

interface SystemAuth {
  username: string;
  keycloak_roles: string[];
  app_user_id: string | null;
  app_role_code: string | null;
  profile: { role_code?: string | null } | null;
}

function getManager(): UserManager {
  if (!userManager) {
    userManager = new UserManager({
      authority: OIDC_AUTHORITY,
      client_id: OIDC_CLIENT_ID,
      redirect_uri: OIDC_REDIRECT_URI,
      post_logout_redirect_uri: OIDC_POST_LOGOUT_URI,
      response_type: "code",
      scope: "openid profile email roles",
      automaticSilentRenew: false,
      loadUserInfo: true,
      userStore: new WebStorageStateStore({ store: window.sessionStorage }),
    });
  }
  return userManager;
}

function getOidcClient(): OidcClient {
  return new OidcClient({
    authority: OIDC_AUTHORITY,
    client_id: OIDC_CLIENT_ID,
    redirect_uri: OIDC_REDIRECT_URI,
    response_type: "code",
    scope: "openid profile email roles",
  });
}

export function clearLocalAuth(): void {
  const returnPath = sessionStorage.getItem(AUTH_RETURN_KEY);

  const keysToRemove: string[] = [];
  for (let index = 0; index < sessionStorage.length; index += 1) {
    const key = sessionStorage.key(index);
    if (!key) continue;
    if (key.startsWith("oidc.")) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach((key) => sessionStorage.removeItem(key));
  sessionStorage.removeItem(APP_AUTH_KEY);

  void getManager().removeUser().catch(() => undefined);

  if (returnPath) {
    sessionStorage.setItem(AUTH_RETURN_KEY, returnPath);
  }
}

export function buildLogoutUrl(idToken: string | undefined, postLogoutRedirectUri: string): string {
  const url = new URL(`${OIDC_AUTHORITY}/protocol/openid-connect/logout`);
  if (idToken) {
    url.searchParams.set("id_token_hint", idToken);
  }
  url.searchParams.set("client_id", OIDC_CLIENT_ID);
  url.searchParams.set("post_logout_redirect_uri", postLogoutRedirectUri);
  return url.toString();
}

/** Единая форма входа Keycloak (без привязки к порталу). */
export async function buildLoginUrl(forceLogin = false): Promise<string> {
  const request = await getOidcClient().createSigninRequest({
    extraQueryParams: forceLogin ? { prompt: "login" } : undefined,
  });
  return request.url;
}

export async function loginWithPassword(username: string, password: string): Promise<{ portal: Portal; user: OidcUser }> {
  clearLocalAuth();

  const body = new URLSearchParams({
    grant_type: "password",
    client_id: OIDC_CLIENT_ID,
    username,
    password,
    scope: "openid profile email roles",
  });

  const response = await fetch(`${OIDC_AUTHORITY}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: string;
      error_description?: string;
    } | null;
    if (payload?.error === "invalid_grant") {
      throw new AuthError("auth_failed", "Проверьте логин и пароль.");
    }
    if (payload?.error === "unauthorized_client") {
      throw new AuthError("auth_failed", "Для клиента hr-web нужно включить Direct Access Grants в Keycloak.");
    }
    throw new AuthError("auth_failed", payload?.error_description ?? "Keycloak не принял запрос входа.");
  }

  const tokens = (await response.json()) as TokenBundle;
  const user = await storeUserFromTokens(tokens);
  const resolvedPortal = await resolvePortalForUser(user);

  if (!resolvedPortal) {
    const resolvedUsername =
      (user.profile.preferred_username as string | undefined) ??
      (user.profile.email as string | undefined) ??
      username;
    clearLocalAuth();
    throw new AuthError(
      "insufficient_roles",
      `У пользователя «${resolvedUsername}» нет системной роли admin, hr или teacher.`,
    );
  }

  return { portal: resolvedPortal, user };
}

export async function performLogout(): Promise<void> {
  const existingUser = await getUser().catch(() => null);
  clearLocalAuth();
  if (existingUser?.id_token) {
    window.location.replace(buildLogoutUrl(existingUser.id_token, OIDC_POST_LOGOUT_URI));
    return;
  }
  window.location.replace("/");
}

export async function handleCallback(): Promise<{ portal: Portal; user: OidcUser }> {
  const user = await getManager().signinRedirectCallback();
  const resolvedPortal = await resolvePortalForUser(user);

  if (!resolvedPortal) {
    const username =
      (user.profile.preferred_username as string | undefined) ??
      (user.profile.email as string | undefined) ??
      "unknown";
    throw new AuthError(
      "insufficient_roles",
      `У пользователя «${username}» нет системной роли admin, hr или teacher.`,
    );
  }

  return { portal: resolvedPortal, user };
}

export async function getUser(): Promise<OidcUser | null> {
  return getManager().getUser();
}

export class AuthError extends Error {
  readonly code: "insufficient_roles" | "auth_failed" | "service_unavailable";

  readonly hint: string;

  constructor(code: AuthError["code"], hint?: string) {
    const messages: Record<AuthError["code"], string> = {
      insufficient_roles: "Недостаточно прав для входа в систему",
      auth_failed: "Не удалось завершить вход",
      service_unavailable: "Сервис авторизации временно недоступен",
    };
    super(messages[code]);
    this.code = code;
    this.hint =
      hint ??
      (code === "insufficient_roles"
        ? "Назначьте пользователю роль admin, hr или teacher в профиле приложения."
        : "Попробуйте войти снова.");
    this.name = "AuthError";
  }
}

function decodeBase64Url(value: string): string {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
  return atob(padded);
}

function decodeTokenRoles(token: string | undefined): string[] {
  if (!token) return [];
  try {
    const segment = token.split(".")[1];
    if (!segment) return [];
    const payload = JSON.parse(decodeBase64Url(segment)) as {
      realm_access?: { roles?: string[] };
      roles?: string[];
      resource_access?: Record<string, { roles?: string[] }>;
    };
    const realmRoles = payload.realm_access?.roles ?? payload.roles ?? [];
    const clientRoles = Object.values(payload.resource_access ?? {}).flatMap((entry) => entry.roles ?? []);
    return [...new Set([...realmRoles, ...clientRoles])];
  } catch {
    return [];
  }
}

function getProfileRoles(user: OidcUser): string[] {
  const realmAccess = user.profile.realm_access as { roles?: string[] } | undefined;
  const directRoles = user.profile.roles as string[] | undefined;
  return realmAccess?.roles ?? directRoles ?? [];
}

export function getRoles(user: OidcUser): string[] {
  return [
    ...new Set([
      ...getProfileRoles(user),
      ...decodeTokenRoles(user.access_token),
      ...decodeTokenRoles(user.id_token),
    ]),
  ];
}

export function hasRequiredRole(user: OidcUser, portal: Portal): boolean {
  const appPortal = resolvePortalFromSystemAuth(readSystemAuth());
  if (appPortal === "admin" || appPortal === portal) {
    return true;
  }
  if (portal === "admin") {
    return false;
  }
  return PORTALS[portal].requiredRoles.some((role) => getRoles(user).includes(role));
}

export interface TokenBundle {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  expires_in: number;
  token_type: string;
  scope?: string;
}

export function resolveDashboard(portal: Portal): string {
  return PORTALS[portal].dashboard;
}

function readSystemAuth(): SystemAuth | null {
  const raw = sessionStorage.getItem(APP_AUTH_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SystemAuth;
  } catch {
    sessionStorage.removeItem(APP_AUTH_KEY);
    return null;
  }
}

function resolvePortalFromSystemAuth(systemAuth: SystemAuth | null): Portal | null {
  return resolvePortalFromAppRole(systemAuth?.app_role_code ?? systemAuth?.profile?.role_code);
}

export async function fetchSystemAuth(accessToken?: string): Promise<SystemAuth | null> {
  const token = accessToken ?? (await getUser())?.access_token;
  if (!token) return null;

  const response = await fetch("/api/v1/auth/me", {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) {
    sessionStorage.removeItem(APP_AUTH_KEY);
    return null;
  }

  const payload = (await response.json()) as SystemAuth;
  sessionStorage.setItem(APP_AUTH_KEY, JSON.stringify(payload));
  return payload;
}

async function resolvePortalForUser(user: OidcUser): Promise<Portal | null> {
  const systemAuth = await fetchSystemAuth(user.access_token).catch(() => readSystemAuth());
  return resolvePortalFromSystemAuth(systemAuth) ?? resolvePortalFromRoles(getRoles(user));
}

export function resolveDashboardForUser(user: OidcUser): string | null {
  const portal = resolvePortalFromSystemAuth(readSystemAuth()) ?? resolvePortalFromRoles(getRoles(user));
  return portal ? resolveDashboard(portal) : null;
}

export async function resolveDashboardForAuthenticatedUser(user: OidcUser): Promise<string | null> {
  const portal = await resolvePortalForUser(user);
  return portal ? resolveDashboard(portal) : null;
}

export async function waitForKeycloakReady(maxAttempts = 30, delayMs = 1000): Promise<void> {
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const response = await fetch(KEYCLOAK_READY_URL, { cache: "no-store" });
      if (response.ok) {
        return;
      }
    } catch {
      // Keycloak ещё поднимается
    }
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }
  throw new AuthError("service_unavailable");
}

function decodeJwtPayload(token: string): Record<string, unknown> {
  const segment = token.split(".")[1];
  if (!segment) {
    throw new Error("Некорректный JWT");
  }
  return JSON.parse(decodeBase64Url(segment)) as Record<string, unknown>;
}

export async function storeUserFromTokens(tokens: TokenBundle): Promise<OidcUser> {
  if (!tokens.id_token) {
    throw new Error("Keycloak не вернул id_token");
  }

  const profile = decodeJwtPayload(tokens.id_token) as OidcUser["profile"];
  const expiresAt = Math.floor(Date.now() / 1000) + tokens.expires_in;

  const user = new User({
    id_token: tokens.id_token,
    access_token: tokens.access_token,
    refresh_token: tokens.refresh_token,
    token_type: tokens.token_type,
    scope: tokens.scope ?? "openid profile email roles",
    profile,
    expires_at: expiresAt,
  });

  await getManager().storeUser(user);
  return user;
}

export async function ensureAuthenticated(portal: Portal): Promise<OidcUser> {
  const user = await getUser();
  if (!user || user.expired) {
    throw new Error("login_required");
  }
  await fetchSystemAuth(user.access_token).catch(() => null);
  if (!hasRequiredRole(user, portal)) {
    throw new Error("forbidden");
  }
  return user;
}

export async function userRequiresPasswordChange(accessToken?: string): Promise<boolean> {
  const token = accessToken ?? (await getUser())?.access_token;
  if (!token) {
    return false;
  }

  const response = await fetch("/api/v1/auth/required-actions", {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) {
    return false;
  }

  const payload = (await response.json()) as { update_password?: boolean };
  return Boolean(payload.update_password);
}

export async function changePassword(newPassword: string, confirmation: string): Promise<void> {
  const user = await getUser();
  if (!user?.access_token) {
    throw new AuthError("auth_failed", "Сессия истекла. Войдите снова.");
  }

  const response = await fetch("/api/v1/auth/change-password", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${user.access_token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      new_password: newPassword,
      confirmation,
    }),
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new AuthError("auth_failed", payload?.detail ?? "Не удалось сменить пароль.");
  }
}
