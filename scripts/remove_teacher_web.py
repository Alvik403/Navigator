"""Remove teacher web portal; keep teacher role for MAX bot + HR."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TEACHER_WEB_FILES = [
    "app/web/public/teacher-dashboard.html",
    "app/web/public/teacher-api.js",
    "app/web/public/teacher-panel.css",
    "app/web/public/teacher-schedule.js",
    "app/web/public/teacher-test.html",
    "app/web/dist/teacher-dashboard.html",
    "app/web/dist/teacher-api.js",
    "app/web/dist/teacher-panel.css",
    "app/web/dist/teacher-schedule.js",
    "app/web/dist/teacher-test.html",
]


def patch_admin() -> None:
    p = ROOT / "app/max-auth/routers/admin.py"
    t = p.read_text(encoding="utf-8")
    t = t.replace(
        "Для ролей admin/hr/teacher укажите логин Keycloak (keycloak_username)",
        "Для ролей admin/hr укажите логин Keycloak (keycloak_username)",
    )
    t = t.replace(
        '{"code": "teacher", "name": "Преподаватель", "web_access": True}',
        '{"code": "teacher", "name": "Инструктор (MAX)", "web_access": False}',
    )
    t = t.replace(
        "Keycloak создаётся только для admin/hr/teacher",
        "Keycloak создаётся только для admin/hr",
    )
    p.write_text(t, encoding="utf-8")


def patch_auth_html() -> None:
    old = """      } else if (lower.includes('teacher') || lower.includes('prep') || lower.includes('prof') || lower.includes('препод')) {
        window.location.href = 'teacher-dashboard.html';
      } else {"""
    new = "      } else {"
    for rel in ("app/web/public/auth.html", "app/web/dist/auth.html"):
        p = ROOT / rel
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        if old in t:
            p.write_text(t.replace(old, new, 1), encoding="utf-8")


def patch_config_ts() -> None:
    p = ROOT / "app/web/src/config.ts"
    t = p.read_text(encoding="utf-8")
    t = t.replace('export type Portal = "hr" | "teacher" | "admin";', 'export type Portal = "hr" | "admin";')
    t = t.replace(
        """  teacher: {
    title: "Портал преподавателя",
    requiredRoles: ["teacher"],
    dashboard: "/teacher-dashboard.html",
  },
""",
        "",
    )
    t = t.replace('  if (roleCode === "teacher") return "teacher";\n', "")
    t = t.replace(
        """  if (canAccessPortal(roles, "teacher")) {
    return "teacher";
  }
""",
        "",
    )
    p.write_text(t, encoding="utf-8")


def patch_auth_ts() -> None:
    p = ROOT / "app/web/src/auth.ts"
    t = p.read_text(encoding="utf-8")
    t = t.replace("admin, hr или teacher", "admin или hr")
    t = t.replace("роль admin, hr или teacher", "роль admin или hr")
    p.write_text(t, encoding="utf-8")


def patch_router_ts() -> None:
    p = ROOT / "app/web/src/router.ts"
    t = p.read_text(encoding="utf-8")
    for s in (
        '  "/login/teacher": () => navigate("/", true),\n',
        '  "/teacher": () => renderProtectedPortal("teacher"),\n',
        '  "/teacher-dashboard.html",\n',
    ):
        t = t.replace(s, "")
    t = t.replace("admin, hr или teacher", "admin или hr")
    p.write_text(t, encoding="utf-8")


def patch_bot_handlers() -> None:
    p = ROOT / "app/max-auth/bot_handlers.py"
    t = p.read_text(encoding="utf-8")
    t = t.replace(
        "# Legacy map only when profile is absent in DB (dev fallback for HR/teacher login).",
        "# Legacy map only when profile is absent in DB (dev fallback for HR login).",
    )
    t = t.replace(
        'if legacy and legacy.get("role") in {"hr_manager", "teacher", "admin"}:',
        'if legacy and legacy.get("role") in {"hr_manager", "admin"}:',
    )
    t = t.replace(
        'role_code={"hr_manager": "hr", "teacher": "teacher", "admin": "admin"}.get(',
        'role_code={"hr_manager": "hr", "admin": "admin"}.get(',
    )
    p.write_text(t, encoding="utf-8")


def patch_auth_guard() -> None:
    old = '        if (role === "teacher") return keycloakRoles.indexOf("teacher") !== -1;\n'
    for rel in ("app/web/public/auth-guard.js", "app/web/dist/auth-guard.js"):
        p = ROOT / rel
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        if old in t:
            p.write_text(t.replace(old, ""), encoding="utf-8")


def delete_teacher_web_files() -> None:
    for rel in TEACHER_WEB_FILES:
        p = ROOT / rel
        if p.exists():
            p.unlink()
            print("deleted", rel)


def patch_hr_test() -> None:
    old = '<a class="logout" href="/teacher-test.html" style="margin-left:8px">Преподаватель</a>\n'
    for rel in ("app/web/public/hr-test.html", "app/web/dist/hr-test.html"):
        p = ROOT / rel
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        if old in t:
            p.write_text(t.replace(old, ""), encoding="utf-8")


def patch_keycloak_theme() -> None:
    login = ROOT / "app/keycloak/themes/max-rass/login/login.ftl"
    t = login.read_text(encoding="utf-8")
    t = t.replace(
        "Введите логин и пароль — система сама откроет нужный портал",
        "Введите логин и пароль — откроется HR-панель или админ-панель",
    )
    t = t.replace(
        '          <span>Преподаватель: <code>teacher.demo</code> / <code>teacher123456</code></span>\n',
        "",
    )
    t = t.replace('placeholder="hr.manager или teacher.demo"', 'placeholder="hr.manager или admin"')
    login.write_text(t, encoding="utf-8")

    err = ROOT / "app/keycloak/themes/max-rass/login/error.ftl"
    t = err.read_text(encoding="utf-8")
    t = t.replace("<code>hr.manager</code> / <code>teacher.demo</code>", "<code>hr.manager</code> / <code>admin</code>")
    err.write_text(t, encoding="utf-8")


def patch_bot_demo_map() -> None:
    p = ROOT / "app/max-auth/bot_handlers.py"
    t = p.read_text(encoding="utf-8")
    t = t.replace('    "teacher.demo": "teacher123456",\n', "")
    old_map = """    "1002": {
        "username": "teacher.demo",
        "password": "teacher123456",
        "label": "Преподаватель",
        "role": "teacher",
    },
"""
    t = t.replace(old_map, "")
    p.write_text(t, encoding="utf-8")


def main() -> None:
    patch_admin()
    patch_auth_html()
    patch_config_ts()
    patch_auth_ts()
    patch_router_ts()
    patch_bot_handlers()
    patch_auth_guard()
    patch_hr_test()
    patch_keycloak_theme()
    patch_bot_demo_map()
    delete_teacher_web_files()
    print("ok")


if __name__ == "__main__":
    main()
