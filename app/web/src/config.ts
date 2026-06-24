export const APP_BUILD_ID = __APP_BUILD_ID__;

export const KEYCLOAK_URL = import.meta.env.VITE_KEYCLOAK_URL ?? window.location.origin;
export const REALM = "max-education";
export const WEB_ORIGIN = import.meta.env.VITE_WEB_ORIGIN ?? window.location.origin;

export type Portal = "hr" | "admin";

/** Единая страница входа */
export const LOGIN_PATH = "/";

/** Единый public OIDC-клиент */
export const OIDC_CLIENT_ID = "hr-web";
export const OIDC_AUTHORITY = `${KEYCLOAK_URL}/realms/${REALM}`;
export const OIDC_REDIRECT_URI = `${WEB_ORIGIN}/callback`;
export const OIDC_POST_LOGOUT_URI = `${WEB_ORIGIN}/`;

export const PORTALS: Record<
  Portal,
  { title: string; requiredRoles: string[]; dashboard: string }
> = {
  hr: {
    title: "HR-портал",
    requiredRoles: ["hr_manager"],
    dashboard: "/hr-dashboard.html",
  },
  admin: {
    title: "Панель администратора",
    requiredRoles: [],
    dashboard: "/admin-dashboard.html",
  },
};

export const AUTH_RETURN_KEY = "max-rass.auth.return";

export function canAccessPortal(roles: string[], portal: Portal): boolean {
  return PORTALS[portal].requiredRoles.some((role) => roles.includes(role));
}

export function resolvePortalFromAppRole(roleCode: string | null | undefined): Portal | null {
  if (roleCode === "admin") return "admin";
  if (roleCode === "hr") return "hr";
  return null;
}

/** HR приоритетнее, если у пользователя несколько ролей Keycloak. */
export function resolvePortalFromRoles(roles: string[]): Portal | null {
  if (canAccessPortal(roles, "hr")) {
    return "hr";
  }
  return null;
}
