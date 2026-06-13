# MAX RASS — локальный стенд

## Адреса

| Сервис | URL |
|--------|-----|
| Приложение (вход) | http://localhost:5173/ |
| Keycloak Admin Console | http://localhost:5173/admin/ |
| Keycloak Admin (напрямую) | http://localhost:8080/admin/ |
| Keycloak realm (API) | http://localhost:8080/realms/max-education |
| MAX Auth API | http://localhost:8025/health |
| Тест запросов к БД | http://localhost:5173/db-test |
| App PostgreSQL | localhost:5433 |

## Учётные данные администратора Keycloak

- **Логин:** `admin`
- **Пароль:** `admin`

Задаются в `docker-compose.yml` (`KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`).

## Как администрировать пользователей

1. Откройте http://localhost:5173/admin/ и войдите как `admin` / `admin`.
2. Выберите realm **max-education** (левый верхний угол).
3. **Users → Create user** — укажите **Username** (email для входа не используется).
4. Откройте пользователя → вкладка **Credentials → Set password**.
5. Введите пароль и включите **Temporary** — при первом входе Keycloak попросит сменить пароль.
6. Вкладка **Role mapping** — назначьте роль `hr_manager`, `teacher` или `admin`.
7. Для входа через MAX добавьте MAX ID в `MAX_USER_MAP_JSON` в `.env` (см. `.env.example`).

### Тестовые пользователи (после импорта realm)

| Username | Пароль (временный) | Роль |
|----------|-------------------|------|
| `hr.manager` | `hr123456` | HR |
| `teacher.demo` | `teacher123456` | Преподаватель |
| `admin` | `admin123456` | Администратор |

## Логика входа и паролей

1. **Первый вход** — администратор создаёт пользователя с временным паролем. Пользователь входит по **имени пользователя** и меняет пароль на форме Keycloak.
2. **Обычный вход** — http://localhost:5173/ (логин + пароль или «Войти через MAX»).
3. **Забыли пароль?** — ссылка на форме ведёт в MAX-бот (`/max?mode=reset`). После подтверждения в боте приходит временный пароль; войдите на сайт и смените пароль.

## Запуск

```powershell
cd app
docker compose up -d --build
```

После изменения realm или клиентов Keycloak:

```powershell
docker compose down -v
docker compose up -d --build
```

Сборка фронтенда:

```powershell
cd web
npm run build
```

## База данных приложения

Сервис `app-postgres` хранит бизнес-данные MAX RASS отдельно от базы Keycloak.
Схема `app` применяется автоматически при старте `max-auth` из файла
`max-auth/sql/001_app_schema.sql`.

Документы:

- `../docs/architecture/max-rass-database-schema.html` — схема БД и логика
- `../docs/testing/database-test-manual.md` — мануал тестирования

Быстрая проверка:

```powershell
curl http://localhost:5173/api/v1/db/health
curl http://localhost:5173/api/v1/db/tables
```
