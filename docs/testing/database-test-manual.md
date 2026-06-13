# MAX RASS — мануал тестирования БД

## 1. Запуск стенда

```powershell
cd app
docker compose up -d --build
```

Сервисы:

- Web: `http://localhost:5173`
- DB test page: `http://localhost:5173/db-test`
- MAX Auth API: `http://localhost:8025/health`
- App Postgres: `localhost:5433`, database `max_rass`, user `max_rass`, password `max_rass`

## 2. Проверка, что БД поднялась

Через браузер:

```text
http://localhost:5173/api/v1/db/health
http://localhost:5173/api/v1/db/tables
```

Ожидаемо:

```json
{"status":"ok"}
```

В списке таблиц должны быть:

- `attendance_marks`
- `group_members`
- `groups`
- `lesson_members`
- `lessons`
- `notifications`
- `profiles`
- `roles`
- `strikes`
- `users`

## 3. Заполнение demo-данными

Откройте `http://localhost:5173/db-test` и нажмите **Заполнить demo**.

Кнопка вызывает:

```http
POST /api/v1/db/seed-demo
```

Demo создаёт:

- HR пользователя
- Куратора
- Преподавателя
- Сотрудника без телефона
- Группу `Backend-26`
- Практическое занятие
- Участника занятия
- Отметку `late`
- Страйк по опозданию
- Уведомление куратору

## 4. Проверочные запросы

### Профили и роли

```sql
SELECT p.user_id, p.last_name, p.first_name, r.code AS role, p.phone, p.id_curator, p.status
FROM app.profiles p
JOIN app.roles r ON r.id = p.role_id
ORDER BY p.last_name;
```

Ожидаемо: 4 demo-профиля. У сотрудника `Ким Мария` телефон `NULL`, а `id_curator` заполнен.

### Занятия и посещаемость

```sql
SELECT l.id AS lesson_id, g.name AS group_name, l.lesson_type, l.starts_at, p.last_name, am.status AS attendance
FROM app.lessons l
JOIN app.groups g ON g.id = l.group_id
JOIN app.lesson_members lm ON lm.lesson_id = l.id
JOIN app.profiles p ON p.user_id = lm.user_id
LEFT JOIN app.attendance_marks am ON am.user_id = lm.user_id AND am.lesson_id = lm.lesson_id
ORDER BY l.starts_at;
```

Ожидаемо: занятие `practice`, группа `Backend-26`, участник `Ким`, посещаемость `late`.

### Страйки

```sql
SELECT s.id, p.last_name, p.first_name, s.reason, s.status, s.strike_number, s.created_at
FROM app.strikes s
JOIN app.profiles p ON p.user_id = s.user_id
ORDER BY s.created_at DESC;
```

Ожидаемо: один активный страйк с `reason = late`.

### Уведомления

```sql
SELECT n.kind, n.sent_at, p.last_name, p.first_name, l.starts_at
FROM app.notifications n
JOIN app.profiles p ON p.user_id = n.delivered_to
JOIN app.lessons l ON l.id = n.lesson_id
ORDER BY n.sent_at DESC;
```

Ожидаемо: уведомление `lesson_reminder_1d`, доставлено куратору, так как сотрудник без телефона.

## 5. Ограничения тестовой страницы

`/db-test` принимает только read-only запросы:

- разрешены `SELECT` и `WITH`
- запрещены `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`
- максимум 200 строк
- timeout запроса 5 секунд

Это нужно, чтобы тестовая страница не ломала схему и данные.

## 6. Проверка напрямую через psql

```powershell
docker compose exec app-postgres psql -U max_rass -d max_rass
```

Внутри psql:

```sql
\dt app.*
SELECT code, name FROM app.roles ORDER BY id;
```

## 7. Пересоздание БД с нуля

Если нужно удалить все данные и применить схему заново:

```powershell
cd app
docker compose down -v
docker compose up -d --build
```

После старта `max-auth` снова применит `app/max-auth/sql/001_app_schema.sql`.
