# HR Dashboard — что реализовано и ограничения

## Реализовано

| Функция | API | UI |
|---------|-----|-----|
| HR видит только свои группы | `GET /hr/groups` фильтр `id_hr` | Вкладка «Группы» |
| Ученики в своих группах | `GET /hr/users?role=employee` + scope | Вкладка «Ученики» |
| Несколько групп у ученика | `group_members` | Колонка «Группа» через запятую |
| CRUD учеников | `POST/PATCH /hr/users`, `POST /hr/users/bulk` | Добавление, редактирование |
| Bulk-import с назначением в группу | `POST /hr/users/bulk` + `POST /hr/groups/{id}/members/bulk` | Модалка «Добавить учеников» |
| Статус active/inactive + причина бана | `PATCH /hr/users/{id}` (`ban_reason`) | Таблица, редактирование |
| Различие ручного бана и бана по страйкам | `profiles.ban_reason`, логика revoke | Колонка «Причина бана» |
| Страйки + автобан при 3 | `POST .../strikes`, `POST .../strikes/revoke` | Кнопки ±, вкладка «Страйки» |
| Апелляции | `GET /hr/appeals`, `POST /hr/appeals/{id}/resolve` | Вкладка «Страйки» |
| Группы и направления | `POST/PATCH /hr/groups`, members | Редактор группы |
| Преподаватели (просмотр) | `GET /hr/teachers` через `lessons` | Вкладка «Преподаватели» |
| **Назначение преподавателя на группу** | `POST /hr/lessons`, `GET /hr/lessons` | Карточка группы, редактор группы, вкладка «Преподаватели» |
| Посещаемость | `GET /hr/reports/attendance/users`, `.../issues` | Вкладка «Посещаемость» |
| Название занятия в посещаемости | `lessons.title` + fallback `lesson_type` | Детали пропусков |
| Расписание занятий HR | `GET /hr/lessons` | Вкладка «Расписание» |
| Сводка HR | `GET /hr/reports/summary` | Виджет на вкладке «Отчёты» |
| Уведомления HR | `GET /hr/notifications` (БД + виртуальные) | Центр уведомлений с фильтрами |
| Отчёты Excel | client-side через `hr-reports.js` | Вкладка «Отчёты» (без PDF) |

### Сводка `GET /hr/reports/summary`

Агрегированные счётчики по HR-scope (или все данные для admin):

- `users_total` — ученики в группах HR
- `groups_active` — активные группы HR
- `strikes_active` — активные страйки у этих учеников
- `appeals_pending` — страйки в статусе `appealed`
- `lessons_week` — занятия за последние 7 дней в группах HR

---

## Миграции БД

Файл `app/max-auth/sql/002_hr_features.sql` (применяется автоматически при старте `max-auth`):

- `app.profiles.ban_reason VARCHAR(255)` — причина бана
- `app.lessons.title VARCHAR(255)` — название занятия (опционально)

---

## Не реализовано / ограничения

| Функция | Почему | Что нужно |
|---------|--------|-----------|
| **Персистентные HR-уведомления о пропусках** | Виртуальные при чтении, не пишутся в БД | Расширить `notification_kind` + nullable `lesson_id` |
| **Статус группы «формируется»** | VARCHAR без enum | CHECK/enum (опционально) |
| **Поиск куратора по ФИО в Excel** | `id_curator` — UUID | Lookup в UI уже есть |
| **Отчёты PDF** | Вне scope | — |
| **Редактирование занятий HR** | Только создание и просмотр | `PATCH /hr/lessons/{id}` |

---

## Файлы интеграции

- Backend: `app/max-auth/domain.py`, `app/max-auth/routers/hr.py`
- SQL: `app/max-auth/sql/002_hr_features.sql`
- Frontend: `app/web/public/hr-api.js`, `app/web/public/hr-dashboard.html`, `app/web/public/components.css`
