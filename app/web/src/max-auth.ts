import {
  resolveDashboardForAuthenticatedUser,
  storeUserFromTokens,
} from "./auth";

export type MaxSessionStatus =
  | "pending"
  | "confirmed"
  | "rejected"
  | "expired"
  | "exchanged"
  | "password_reset";

export interface MaxStartResponse {
  session_id: string;
  auth_token: string;
  bot_url: string;
  expires_at: number;
  poll_interval_ms: number;
  message: string;
}

export interface MaxStatusResponse {
  session_id: string;
  status: MaxSessionStatus;
  expires_at: number;
  keycloak_username?: string | null;
  temp_password?: string | null;
}

export interface KeycloakTokenResponse {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  expires_in: number;
  token_type: string;
  scope?: string;
}

const MAX_SESSION_KEY = "max-rass.max.session";

export function saveMaxSessionId(sessionId: string): void {
  sessionStorage.setItem(MAX_SESSION_KEY, sessionId);
}

export function getMaxSessionId(): string | null {
  return sessionStorage.getItem(MAX_SESSION_KEY);
}

export function clearMaxSessionId(): void {
  sessionStorage.removeItem(MAX_SESSION_KEY);
}

export async function startMaxLogin(): Promise<MaxStartResponse> {
  const response = await fetch("/api/v1/auth/max/start", { method: "POST" });
  if (!response.ok) {
    throw new Error("Не удалось начать вход через MAX");
  }
  const data = (await response.json()) as MaxStartResponse;
  saveMaxSessionId(data.session_id);
  return data;
}

export async function startMaxPasswordReset(): Promise<MaxStartResponse> {
  const response = await fetch("/api/v1/auth/max/reset/start", { method: "POST" });
  if (!response.ok) {
    throw new Error("Не удалось начать восстановление пароля через MAX");
  }
  const data = (await response.json()) as MaxStartResponse;
  saveMaxSessionId(data.session_id);
  return data;
}

export async function getMaxStatus(sessionId: string): Promise<MaxStatusResponse> {
  const response = await fetch(`/api/v1/auth/max/status/${sessionId}`, { cache: "no-store" });
  if (response.status === 410) {
    return {
      session_id: sessionId,
      status: "expired",
      expires_at: Math.floor(Date.now() / 1000),
    };
  }
  if (!response.ok) {
    throw new Error("Не удалось проверить статус входа");
  }
  return (await response.json()) as MaxStatusResponse;
}

export async function exchangeMaxSession(sessionId: string): Promise<KeycloakTokenResponse> {
  const response = await fetch("/api/v1/auth/max/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail ?? "Не удалось получить токен");
  }
  return (await response.json()) as KeycloakTokenResponse;
}

export async function completeMaxLogin(tokens: KeycloakTokenResponse): Promise<string> {
  const user = await storeUserFromTokens(tokens);
  clearMaxSessionId();

  const dashboard = await resolveDashboardForAuthenticatedUser(user);
  if (!dashboard) {
    throw new Error("Не удалось определить портал");
  }
  return dashboard;
}

export function openMaxBotInNewTab(botUrl: string): Window | null {
  return window.open(botUrl, "_blank", "noopener,noreferrer");
}
