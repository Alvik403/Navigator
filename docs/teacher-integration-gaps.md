# Teacher Dashboard — что реализовано и ограничения

## Реализовано

| Функция | API | UI |
|---------|-----|-----|
| Список рабочих групп (через занятия) | `GET /teacher/groups` | Вкладка «Группы» |
| Просмотр расписания всех преподавателей | `GET /teacher/lessons?all_teachers=true` | Вкладка «Расписание», временная сетка 08:00–20:00 |
| Свои занятия выделены | `teacher_id` в данных | Синие блоки `.mine`, чужие — `.other` |
| Пересечения и конфликты на календаре | client-side `teacher-schedule.js` | Lane packing, бейдж «!», фильтр Все/Мои/Конфликты |
| Проверка конфликтов при создании занятия | `detectConflicts` / `validateDraft` | Модалка + смежные занятия с причинами |
| Создание / редактирование / удаление своих занятий | `POST/PATCH/DELETE /teacher/lessons` | Модалка занятия |
| Отметка посещаемости | `GET/POST /teacher/lessons/{id}/attendance` | Главная → отметка участников |
| Отчёт по группам и ученикам | `GET /teacher/reports/attendance/*` | Вкладка «Отчёт» |
| Excel-выгрузка отчёта | client-side (XLSX CDN) | Кнопка «Выгрузить Excel» |
| История изменений отметок | `GET /teacher/attendance/history` + таблица `attendance_mark_history` | Отчёт + модалка «История» на главной |
| Название занятия (`title`) | `lessons.title` | Поле «Тема» в модалке |

### Миграция БД

Файл `app/max-auth/sql/003_teacher_attendance_history.sql`:

- Таблица `app.attendance_mark_history` — аудит смен статуса present/late/absent
- Запись при `save_lesson_attendance`, если статус изменился

---

## Не реализовано / ограничения

| Функция | Почему | Что нужно |
|---------|--------|-----------|
| **Замечания к отметкам** | Нет поля в схеме | Колонка `note` в `attendance_marks` |
| **Редактирование подгруппы занятия** | `PATCH` не меняет `lesson_members` | Endpoint синхронизации участников |
| **Курсы (направления) как отдельные карточки** | В API только рабочие группы + `parent_name` | JOIN родительских групп или HR-scope |
| **Кураторы в общем списке users** | Загружаются только участники групп | Отдельный lookup кураторов |
| **Первичная отметка в истории** | `old_status = NULL` при первом сохранении | Ожидаемое поведение аудита |
| **Admin как преподаватель** | Admin видит все отчёты без teacher-scope | По дизайну для admin-роли |
| **Server-side проверка конфликтов** | Сейчас только на клиенте | `GET /teacher/lessons/conflicts?from=&to=` (фаза 1.5) |

### Конфликты (клиент)

Для **своего** занятия конфликт = пересечение по времени и хотя бы одно из:

- тот же преподаватель (двойное бронирование);
- тот же кабинет (`place`);
- та же группа;
- общий ученик в `lesson_members`.

Логика в `app/web/public/teacher-schedule.js` — единый источник для календаря, модалки и фильтра «Конфликты».

---

## Файлы интеграции

- Backend: `app/max-auth/domain.py`, `app/max-auth/routers/teacher.py`
- SQL: `app/max-auth/sql/003_teacher_attendance_history.sql`
- Frontend: `app/web/public/teacher-api.js`, `app/web/public/teacher-schedule.js`, `app/web/public/teacher-dashboard.html`, `app/web/public/teacher-panel.css`

## Запуск после изменений

```bash
cd app/web && npm run build
docker compose build max-auth && docker compose up -d max-auth app-postgres
# при необходимости: POST /api/v1/db/seed-demo
```

Логин для проверки: `teacher.demo` → UUID `33333333-3333-3333-3333-333333333333`.
