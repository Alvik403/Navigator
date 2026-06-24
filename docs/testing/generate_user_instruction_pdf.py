"""Generate MAX RASS user instruction PDF into Downloads folder."""

from pathlib import Path

from fpdf import FPDF

OUTPUT = Path.home() / "Downloads" / "MAX-RASS-instrukciya.pdf"
FONT_REG = Path(r"C:\Windows\Fonts\arial.ttf")
FONT_BOLD = Path(r"C:\Windows\Fonts\arialbd.ttf")


class InstructionPDF(FPDF):
    def __init__(self) -> None:
        super().__init__()
        self.add_font("Arial", "", str(FONT_REG))
        self.add_font("Arial", "B", str(FONT_BOLD))
        self.set_auto_page_break(auto=True, margin=18)

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font("Arial", "B", 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "MAX RASS — инструкция для пользователя", align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Arial", "", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Страница {self.page_no()}", align="C")

    def title_block(self, title: str, subtitle: str) -> None:
        self.set_font("Arial", "B", 20)
        self.set_text_color(46, 125, 50)
        self.multi_cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)
        self.set_font("Arial", "", 11)
        self.set_text_color(60, 60, 60)
        self.multi_cell(0, 6, subtitle, new_x="LMARGIN", new_y="NEXT")
        self.ln(6)

    def section(self, text: str) -> None:
        self.ln(3)
        self.set_font("Arial", "B", 13)
        self.set_text_color(46, 125, 50)
        self.multi_cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def paragraph(self, text: str) -> None:
        self.set_font("Arial", "", 11)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def bullet(self, text: str) -> None:
        self.set_font("Arial", "", 11)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 6, f"  •  {text}", new_x="LMARGIN", new_y="NEXT")

    def numbered(self, n: int, text: str) -> None:
        self.set_font("Arial", "", 11)
        self.set_text_color(30, 30, 30)
        self.multi_cell(0, 6, f"  {n}. {text}", new_x="LMARGIN", new_y="NEXT")

    def table_row(self, col1: str, col2: str, header: bool = False) -> None:
        if header:
            self.set_font("Arial", "B", 10)
            self.set_fill_color(232, 245, 233)
        else:
            self.set_font("Arial", "", 10)
            self.set_fill_color(255, 255, 255)
        self.set_text_color(30, 30, 30)
        self.cell(55, 8, col1, border=1, fill=True)
        self.cell(0, 8, col2, border=1, fill=True, new_x="LMARGIN", new_y="NEXT")


def build() -> None:
    pdf = InstructionPDF()
    pdf.set_margins(18, 18, 18)
    pdf.add_page()

    pdf.title_block(
        "MAX RASS",
        "Краткая инструкция для пользователя. Система учёта занятий, посещаемости и уведомлений через MAX.",
    )

    pdf.section("1. Как открыть систему")
    pdf.paragraph("Откройте браузер (Chrome, Edge, Firefox) и перейдите по адресу:")
    pdf.set_font("Arial", "B", 11)
    pdf.set_text_color(21, 101, 192)
    pdf.multi_cell(0, 7, "http://localhost:5173/", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.paragraph("На главной странице отображается форма входа.")

    pdf.section("2. Тестовые учётные записи")
    pdf.paragraph("Для проверки системы используйте готовые логины:")
    pdf.ln(1)
    pdf.table_row("Логин", "Пароль / роль", header=True)
    pdf.table_row("hr.manager", "hr123456 — HR-менеджер")
    pdf.table_row("teacher.demo", "teacher123456 — преподаватель")
    pdf.table_row("admin", "admin123456 — администратор")
    pdf.ln(3)

    pdf.section("3. Вход в систему")
    pdf.numbered(1, "Введите логин и пароль на странице входа.")
    pdf.numbered(2, "Нажмите кнопку «Войти».")
    pdf.numbered(3, "После успешного входа откроется панель в зависимости от вашей роли.")
    pdf.ln(2)
    pdf.paragraph("Альтернативный способ — кнопка «Войти через MAX»:")
    pdf.bullet("Нажмите «Войти через MAX» на странице входа.")
    pdf.bullet("Откроется бот MAX — подтвердите вход.")
    pdf.bullet("Вернитесь на сайт — вход выполнится автоматически.")
    pdf.ln(2)
    pdf.paragraph("Если забыли пароль:")
    pdf.bullet("Нажмите «Забыли пароль?» на форме входа.")
    pdf.bullet("Подтвердите сброс в боте MAX.")
    pdf.bullet("Получите временный пароль, войдите и смените его на новый.")

    pdf.section("4. HR-панель")
    pdf.paragraph("Доступна после входа под учётной записью HR (hr.manager).")
    pdf.bullet("Ученики — просмотр, добавление и редактирование учеников.")
    pdf.bullet("Рабочие группы — создание групп и управление составом.")
    pdf.bullet("Преподаватели и кураторы — списки сотрудников.")
    pdf.bullet("Посещаемость — просмотр отметок по занятиям.")
    pdf.bullet("Расписание — занятия по группам.")
    pdf.bullet("Страйки — выписать или отменить страйк за опоздание/пропуск.")
    pdf.bullet("Уведомления — история отправленных напоминаний.")
    pdf.bullet("Отчёты — сводные данные по посещаемости.")

    pdf.section("5. Панель преподавателя")
    pdf.paragraph("Доступна после входа под учётной записью преподавателя (teacher.demo).")
    pdf.bullet("Главная — ближайшее занятие и отметка посещаемости.")
    pdf.bullet("Расписание — календарь занятий, создание и редактирование.")
    pdf.bullet("Группы — список рабочих групп преподавателя.")
    pdf.bullet("Отчёт — посещаемость по группам и ученикам.")
    pdf.ln(2)
    pdf.paragraph("Как отметить посещаемость:")
    pdf.numbered(1, "На главной выберите занятие.")
    pdf.numbered(2, "Отметьте каждого ученика: присутствует, опоздал или отсутствует.")
    pdf.numbered(3, "Нажмите «Сохранить».")

    pdf.add_page()

    pdf.section("6. MAX-бот")
    pdf.paragraph("Бот MAX используется для:")
    pdf.bullet("подтверждения входа на сайт;")
    pdf.bullet("восстановления пароля;")
    pdf.bullet("напоминаний о занятиях (за сутки и за 3 часа).")
    pdf.ln(2)
    pdf.paragraph(
        "Если у ученика не указан телефон, напоминание отправляется его куратору."
    )

    pdf.section("7. Быстрая проверка (5 минут)")
    pdf.numbered(1, "Откройте http://localhost:5173/ — страница входа загружается.")
    pdf.numbered(2, "Войдите как hr.manager — открывается HR-панель, видны вкладки.")
    pdf.numbered(3, "Выйдите и войдите как teacher.demo — открывается панель преподавателя.")
    pdf.numbered(4, "На главной преподавателя выберите занятие и проверьте отметку посещаемости.")
    pdf.numbered(5, "При настроенном MAX-боте проверьте вход через MAX.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUTPUT))
    print(f"Created: {OUTPUT}")


if __name__ == "__main__":
    build()
