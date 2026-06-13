# MAX RASS — мануал тестирования БД

## Запуск

```powershell
cd app
docker compose up -d --build
```

Откройте:

- `http://localhost:5173/db-test`
- `http://localhost:5173/api/v1/db/health`
- `http://localhost:5173/api/v1/db/tables`

## Demo-данные

На странице `/db-test` нажмите **Заполнить demo**.

Будут созданы HR, куратор, преподаватель, сотрудник без телефона, группа, занятие, отметка `late`, страйк и уведомление куратору.

## Проверочные запросы

```sql
SELECT p.user_id, p.last_name, p.first_name, r.code AS role, p.phone, p.id_curator, p.status
FROM app.profiles p
JOIN app.roles r ON r.id = p.role_id
ORDER BY p.last_name;
```

```sql
SELECT l.id AS lesson_id, g.name AS group_name, l.lesson_type, l.starts_at, p.last_name, am.status AS attendance
FROM app.lessons l
JOIN app.groups g ON g.id = l.group_id
JOIN app.lesson_members lm ON lm.lesson_id = l.id
JOIN app.profiles p ON p.user_id = lm.user_id
LEFT JOIN app.attendance_marks am ON am.user_id = lm.user_id AND am.lesson_id = lm.lesson_id
ORDER BY l.starts_at;
```

```sql
SELECT s.id, p.last_name, p.first_name, s.reason, s.status, s.strike_number, s.created_at
FROM app.strikes s
JOIN app.profiles p ON p.user_id = s.user_id
ORDER BY s.created_at DESC;
```

```sql
SELECT n.kind, n.sent_at, p.last_name, p.first_name, l.starts_at
FROM app.notifications n
JOIN app.profiles p ON p.user_id = n.delivered_to
JOIN app.lessons l ON l.id = n.lesson_id
ORDER BY n.sent_at DESC;
```

## Ограничения

Страница выполняет только `SELECT` и `WITH`, максимум 200 строк, timeout 5 секунд.

## Полная версия

Подробный мануал хранится в `docs/testing/database-test-manual.md`.
