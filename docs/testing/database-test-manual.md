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

- `conveyor_slots`
- `attendance_marks`
- `group_members`
- `groups`
- `lesson_members`
- `lessons`
- `notifications`
- `profiles`
- `roles`
- `strikes`
- `track_teachers`
- `tracks`
- `user_tracks`
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
- Треки `Бетонщик`, `Арматурщик`, `Водитель бетономешалки`
- Конвейерные слоты
- Параллельные назначения пользователя на несколько треков
- Группу `Backend-26`
- Практическое занятие
- Участника занятия
- Отметку `late`
- Страйк по опозданию
- Страйк преподавателю без блокировки
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
SELECT l.id AS lesson_id, g.name AS group_name, t.name AS track_name, cs.name AS slot_name,
       l.lesson_type, l.starts_at, p.last_name, lm.role_in_lesson, am.status AS attendance
FROM app.lessons l
JOIN app.groups g ON g.id = COALESCE(l.reporting_group_id, l.group_id)
LEFT JOIN app.tracks t ON t.id = l.track_id
LEFT JOIN app.conveyor_slots cs ON cs.id = l.slot_id
JOIN app.lesson_members lm ON lm.lesson_id = l.id
JOIN app.profiles p ON p.user_id = lm.user_id
LEFT JOIN app.attendance_marks am ON am.user_id = lm.user_id AND am.lesson_id = lm.lesson_id
ORDER BY l.starts_at;
```

Ожидаемо: у занятий есть отчётная группа, трек/слот, участники с `role_in_lesson = employee` и преподаватель с `role_in_lesson = teacher`.

### Треки

```sql
SELECT t.name, t.practice_required, count(ut.user_id) AS users_total
FROM app.tracks t
LEFT JOIN app.user_tracks ut ON ut.track_id = t.id AND ut.status = 'active'
GROUP BY t.id, t.name, t.practice_required
ORDER BY t.name;
```

Ожидаемо: треки `Бетонщик`, `Арматурщик`, `Водитель бетономешалки`; один пользователь может быть назначен на несколько треков.

### Страйки

```sql
SELECT s.id, p.last_name, p.first_name, r.code AS role, s.target_role,
       s.reason, s.status, s.strike_number, s.created_at
FROM app.strikes s
JOIN app.profiles p ON p.user_id = s.user_id
JOIN app.roles r ON r.id = p.role_id
ORDER BY s.created_at DESC;
```

Ожидаемо: есть страйки учеников и преподавателя; преподавательские страйки не переводят профиль в `inactive`.

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
