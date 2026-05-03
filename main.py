# main.py

import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Optional
from datetime import date, datetime, timedelta

from fastapi import (
    FastAPI, Request, HTTPException, Depends, status,
    Form, UploadFile, File, Cookie)

from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from database import db_instance, get_db
from init_db import create_tables, seed_test_data, ensure_tables_exist



# Простая аутентификация (прямое сравнение строк)
def verify_password(plain: str, stored: str):
    return plain == stored


# ------------------- Управление сессиями -------------------
active_sessions = {}  # token -> {"user_id": int, "user_type": str, "login": str}

def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def get_current_user(
        session_token: Optional[str] = Cookie(None),
        db_cursor = Depends(get_db)
) -> Optional[dict]:
    """
       Возвращает словарь с данными текущего пользователя или None.
       Структура: {
           "id": int,
           "name": str,
           "login": str,
           "type": "parent" | "trainer",
           "is_admin": bool (только для trainer)
       }
       """

    # Текущий пользователь не найден
    if not session_token or session_token not in active_sessions:
        return None

    session = active_sessions[session_token]
    user_id = session["user_id"]
    user_type = session["user_type"]

    # Если админ
    if user_type == "admin":
        db_cursor.execute(
            "SELECT id, full_name, login FROM admins WHERE id = ?",
            (user_id,)
        )
        user = db_cursor.fetchone()
        if user:
            return {
                "id": user["id"],
                "name": user["full_name"],
                "login": user["login"],
                "type": "admin"
            }
    # Если тренер
    elif user_type == "trainer":
        db_cursor.execute(
            "SELECT id, full_name, login FROM trainers WHERE id = ?",
            (user_id,)
        )
        user = db_cursor.fetchone()
        if user:
            return {
                "id": user["id"],
                "name": user["full_name"],
                "login": user["login"],
                "type": "trainer"
            }
    # Если родитель
    elif user_type == "parent":
        db_cursor.execute(
            "SELECT id, full_name, phone FROM parents WHERE id = ?",
            (user_id,)
        )
        user = db_cursor.fetchone()
        if user:
            return {
                "id": user["id"],
                "name": user["full_name"],
                "login": user["phone"],  # логин = телефон
                "type": "parent"
            }
    return None


# Проверка ролей/прав
def require_parent(request: Request, current_user: Optional[dict]):
    if not current_user or current_user["type"] != "parent":
        return templates.TemplateResponse(
            request,
            "access_denied.html",
            {
                "request": request,
                "message": "Эта страница доступна только родителям."
            }
        )
    return None

def check_trainer(request: Request, current_user: Optional[dict]):
    if not current_user or current_user["type"] != "trainer":
        return templates.TemplateResponse(
            request,
            "access_denied.html",
            {
                "request": request,
                "message": "Эта страница доступна только тренерам."
            }
        )
    return None

def check_admin(request: Request, current_user: Optional[dict]):
    if not current_user or current_user["type"] != "trainer" or not current_user.get("is_admin"):
        return templates.TemplateResponse(
            request,
            "access_denied.html",
            {
                "request": request,
                "message": "Эта страница доступна только администратору."
            }
        )
    return None

# Для удобства: комбинированные проверки (например, тренер или админ)
def require_trainer_or_admin(current_user: Optional[dict]):
    if not current_user or current_user["type"] not in ("trainer", "admin"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")

def require_parent_or_self_child(current_user: Optional[dict], child_id: int, db_cursor):
    """Проверяет, что родитель имеет доступ к указанному ребёнку (своему)."""
    if current_user["type"] == "admin":
        return True
    if current_user["type"] == "parent":
        db_cursor.execute("SELECT id FROM children WHERE id = ? AND parent_id = ?", (child_id, current_user["id"]))
        return db_cursor.fetch


# Вспомогательная функция для проверки доступа тренера к группе
def can_manage_group(group_id: int, current_user: dict, db_cursor) -> bool:
    """Проверяет, может ли текущий пользователь (тренер или админ) управлять группой."""
    if current_user["type"] == "admin":
        return True
    if current_user["type"] == "trainer":
        db_cursor.execute("SELECT trainer_id FROM groups WHERE id = ?", (group_id,))
        group = db_cursor.fetchone()
        return group is not None and group["trainer_id"] == current_user["id"]
    return False


# Инициализация базы данных (добавление полей при необходимости)
def upgrade_database():
    """
    Приводит структуру БД к актуальному состоянию:
    - Создаёт таблицу admins, если её нет.
    - Добавляет password_hash в parents, если нет.
    - Создаёт тестового администратора, если таблица admins пуста.
    """
    with db_instance.get_connection() as conn:
        cursor = conn.cursor()

        # 1. Создаём таблицу admins, если её нет
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name VARCHAR(255) NOT NULL,
                login VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Добавляем тестового администратора, если таблица пуста
        cursor.execute("SELECT COUNT(*) FROM admins")
        if cursor.fetchone()[0] == 0:
            # Логин: admin, пароль: admin (временное решение, без хеширования)
            cursor.execute(
                "INSERT INTO admins (full_name, login, password_hash) VALUES (?, ?, ?)",
                ("Администратор системы", "admin", "admin")
            )
            print("✅ Создан тестовый администратор: login='admin', password='admin'")

        # 2. Для таблицы parents: добавляем password_hash (если нет)
        cursor.execute("PRAGMA table_info(parents)")
        columns = [col[1] for col in cursor.fetchall()]
        if "password_hash" not in columns:
            cursor.execute("ALTER TABLE parents ADD COLUMN password_hash VARCHAR(255)")
            # Для существующих родителей проставляем пароль = телефон
            cursor.execute("SELECT id, phone FROM parents")
            for row in cursor.fetchall():
                cursor.execute(
                    "UPDATE parents SET password_hash = ? WHERE id = ?",
                    (row["phone"], row["id"])
                )
            print("✅ Добавлено поле password_hash в таблицу parents")

        conn.commit()

# Жизненный цикл приложения
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Управляет жизненным циклом приложения:
    - при запуске проверяет и инициализирует БД
    - при завершении закрывает соединение с БД
    """

    print("Запуск приложения...")

    # Проверяем, существуют ли таблицы       ensure_tables_exist() создаёт таблицы, если их нет
    tables_created = ensure_tables_exist() # и возвращает True, если были созданы

    # Если таблицы были только что созданы, заполняем их тестовыми данными
    if tables_created:
        print("Таблицы созданы, заполняем тестовыми данными...")
        seed_test_data()
    else: # Таблицы уже существуют. Проверка наличия данных
        from database import get_db_cursor
        with get_db_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM trainers")
            if cursor.fetchone()[0] == 0:
                seed_test_data()
    upgrade_database()
    print("Приложение готово")

    yield  # Здесь работает само приложение

    # Завершение работы
    print("Остановка приложения, закрытие соединения с БД...")
    db_instance.close()
    print("Соединение закрыто")


# Инициализация FastAPI
app = FastAPI(
    title="pool_crm",
    description="CRM для бассейна (школьные группы)",
    version="1.0.0",
    lifespan=lifespan
)

# Подключение статики и шаблонов
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")



# ======================== ПУБЛИЧНЫЕ МАРШРУТЫ (не требуют авторизации) ========================

# ---------- Главная страница (информация о школе) ----------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request}
    )


# ---------- Страница входа для всех пользователей ----------
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request}
    )

@app.post("/login")
async def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    db_cursor = Depends(get_db)
):
    """
    Обработка входа:
    - сначала проверяем среди администраторов
    - затем среди тренеров
    - затем среди родителей (по телефону)
    """
    # 1. Проверка администратора
    db_cursor.execute(
        "SELECT id, full_name, login, password_hash FROM admins WHERE login = ?",
        (username,)
    )
    admin = db_cursor.fetchone()
    if admin and verify_password(password, admin["password_hash"]):
        token = generate_session_token()
        active_sessions[token] = {
            "user_id": admin["id"],
            "user_type": "admin",
            "login": admin["login"]
        }
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie("session_token", token, httponly=True)
        return response

    # 2. Проверка тренера
    db_cursor.execute(
        "SELECT id, full_name, login, password_hash FROM trainers WHERE login = ?",
        (username,)
    )
    trainer = db_cursor.fetchone()
    if trainer and verify_password(password, trainer["password_hash"]):
        token = generate_session_token()
        active_sessions[token] = {
            "user_id": trainer["id"],
            "user_type": "trainer",
            "login": trainer["login"]
        }
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie("session_token", token, httponly=True)
        return response

    # 3. Проверка родителя (по телефону)
    db_cursor.execute(
        "SELECT id, full_name, phone, password_hash FROM parents WHERE phone = ?",
        (username,)
    )
    parent = db_cursor.fetchone()
    if parent and verify_password(password, parent["password_hash"]):
        token = generate_session_token()
        active_sessions[token] = {
            "user_id": parent["id"],
            "user_type": "parent",
            "login": parent["phone"]
        }
        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie("session_token", token, httponly=True)
        return response

    # Если ничего не подошло — вернуться на страницу входа с ошибкой
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "error": "Неверный логин или пароль"
        }
    )

@app.get("/logout")
async def logout():
    """Выход из системы — удаляем сессию и cookie."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response


# ---------- Подача заявки ----------
@app.get("/apply", response_class=HTMLResponse)
async def apply_form(request: Request):
    """
    Публичная форма для подачи заявки на зачисление.
    """
    return templates.TemplateResponse(
        request,
        "application_form.html",
        {"request": request}
    )

@app.post("/apply")
async def submit_application(
    request: Request,
    parent_full_name: Annotated[str, Form()],
    parent_phone: Annotated[str, Form()],
    child_full_name: Annotated[str, Form()],
    child_age: Annotated[int, Form()],
    school_name: Annotated[str, Form()],
    shift: Annotated[str, Form()],
    parent_email: Annotated[Optional[str], Form()] = None,
    child_class: Annotated[Optional[int], Form()] = None,
    swimming_years: Annotated[int, Form()] = 1,
    desired_lessons_per_week: Annotated[int, Form()] = 2,
    db_cursor = Depends(get_db)
):
    """
    Обработка и сохранение заявки.
    """
    # Простая валидация
    if not (3 <= child_age <= 17):
        return templates.TemplateResponse(
            request,
            "application_form.html",
            {
                "request": request,
                "error": "Возраст ребёнка должен быть от 3 до 17 лет",
                "form_data": dict(await request.form())  # для возврата введённых данных
            }
        )

    if shift not in ("day", "evening"):
        shift = "day"

    if desired_lessons_per_week not in (1, 2, 3):
        desired_lessons_per_week = 2

    # Сохраняем заявку
    db_cursor.execute(
        """
        INSERT INTO applications
        (parent_full_name, parent_phone, parent_email, child_full_name, child_age,
         child_class, school_name, swimming_years, shift, desired_lessons_per_week, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new')
        """,
        (parent_full_name, parent_phone, parent_email, child_full_name, child_age,
         child_class, school_name, swimming_years, shift, desired_lessons_per_week)
    )
    db_cursor.connection.commit()

    # Отображаем страницу успеха
    return templates.TemplateResponse(
        request,
        "application_success.html",
        {
            "request": request,
            "message": "Заявка успешно отправлена! Наш администратор свяжется с вами в ближайшее время."
        }
    )



# ======================== РОДИТЕЛЬ ========================

# ---------- Личный кабинет ----------
@app.get("/parent/profile", response_class=HTMLResponse)
async def parent_profile(
    request: Request,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """
    Личный кабинет родителя — показывает список всех детей.
    """
    require_parent(current_user)
    parent_id = current_user["id"]

    # Выбираем всех детей родителя
    db_cursor.execute(
        """
        SELECT id, full_name, age, class_number, school_name,
               swimming_years, shift, desired_lessons_per_week
        FROM children
        WHERE parent_id = ?
        ORDER BY full_name
        """,
        (parent_id,)
    )
    children = db_cursor.fetchall()

    # Для каждого ребёнка узнаем его текущую группу
    children_with_group = []
    for child in children:
        db_cursor.execute(
            """
            SELECT g.id, g.name, g.shift, t.full_name as trainer_name
            FROM enrollments e
            JOIN groups g ON e.group_id = g.id
            LEFT JOIN trainers t ON g.trainer_id = t.id
            WHERE e.child_id = ? AND e.is_active = 1
            """,
            (child["id"],)
        )
        group = db_cursor.fetchone()
        children_with_group.append({
            "id": child["id"],
            "full_name": child["full_name"],
            "age": child["age"],
            "class_number": child["class_number"],
            "school_name": child["school_name"],
            "swimming_years": child["swimming_years"],
            "shift": child["shift"],
            "desired_lessons_per_week": child["desired_lessons_per_week"],
            "group": dict(group) if group else None
        })

    return templates.TemplateResponse(
        request,
        "parent_profile.html",
        {
            "request": request,
            "children": children_with_group,
            "current_user": current_user
        }
    )


# ---------- Профили детей ----------
@app.get("/parent/child/{child_id}", response_class=HTMLResponse)
async def child_details(
    request: Request,
    child_id: int,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """
    Детальная страница ребёнка: информация, группа, расписание, посещаемость.
    """
    require_parent(current_user)
    parent_id = current_user["id"]

    # Проверяем, что ребёнок принадлежит этому родителю
    db_cursor.execute(
        "SELECT * FROM children WHERE id = ? AND parent_id = ?",
        (child_id, parent_id)
    )
    child = db_cursor.fetchone()
    if not child:
        raise HTTPException(status_code=404, detail="Ребёнок не найден")

    # Текущее зачисление
    db_cursor.execute(
        """
        SELECT g.id, g.name, g.shift, g.min_age, g.max_age, g.max_students,
               t.full_name as trainer_name, e.enrolled_at
        FROM enrollments e
        JOIN groups g ON e.group_id = g.id
        LEFT JOIN trainers t ON g.trainer_id = t.id
        WHERE e.child_id = ? AND e.is_active = 1
        """,
        (child_id,)
    )
    enrollment = db_cursor.fetchone()
    group = dict(enrollment) if enrollment else None

    # Расписание занятий группы (если есть)
    schedule_items = []
    if group:
        db_cursor.execute(
            """
            SELECT id, weekday, start_time, end_time, location, is_recurring, single_date
            FROM schedule
            WHERE group_id = ?
            ORDER BY weekday, start_time
            """,
            (group["id"],)
        )
        schedule_items = db_cursor.fetchall()

    # Посещаемость: последние 30 дней
    today = date.today()
    # Найдём enrollment_id для этого ребёнка
    if group:
        db_cursor.execute("SELECT id FROM enrollments WHERE child_id = ? AND is_active = 1", (child_id,))
        enrollment_record = db_cursor.fetchone()
        if enrollment_record:
            db_cursor.execute(
                """
                SELECT date, status
                FROM attendance
                WHERE enrollment_id = ?
                ORDER BY date DESC
                LIMIT 30
                """,
                (enrollment_record["id"],)
            )
            attendance = db_cursor.fetchall()
        else:
            attendance = []
    else:
        attendance = []

    return templates.TemplateResponse(
        request,
        "child_details.html",
        {
            "request": request,
            "child": dict(child),
            "group": group,
            "schedule": schedule_items,
            "attendance": attendance,
            "current_user": current_user
        }
    )



# ======================== ТРЕНЕР ========================

# ---------- Личный кабинет тренера ----------
@app.get("/trainer/dashboard", response_class=HTMLResponse)
async def trainer_dashboard(
    request: Request,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Дашборд тренера: список групп (админ видит все, тренер — только свои)."""
    require_trainer_or_admin(current_user)

    if current_user["type"] == "admin":
        db_cursor.execute(
            """
            SELECT g.id, g.name, g.min_age, g.max_age, g.max_students, g.shift,
                   t.full_name as trainer_name, COUNT(e.id) as enrolled
            FROM groups g
            LEFT JOIN trainers t ON g.trainer_id = t.id
            LEFT JOIN enrollments e ON e.group_id = g.id AND e.is_active = 1
            GROUP BY g.id
            ORDER BY g.name
            """
        )
    else:  # тренер
        db_cursor.execute(
            """
            SELECT g.id, g.name, g.min_age, g.max_age, g.max_students, g.shift,
                   t.full_name as trainer_name, COUNT(e.id) as enrolled
            FROM groups g
            LEFT JOIN trainers t ON g.trainer_id = t.id
            LEFT JOIN enrollments e ON e.group_id = g.id AND e.is_active = 1
            WHERE g.trainer_id = ?
            GROUP BY g.id
            ORDER BY g.name
            """,
            (current_user["id"],)
        )
    groups = db_cursor.fetchall()

    return templates.TemplateResponse(
        request,
        "trainer_dashboard.html",
        {
            "request": request,
            "groups": groups,
            "current_user": current_user
        }
    )


# ---------- Просмотр группы (ученики + расписание) ----------
@app.get("/trainer/group/{group_id}", response_class=HTMLResponse)
async def group_view(
    request: Request,
    group_id: int,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Детальная страница группы: список учеников, расписание, кнопки действий."""
    require_trainer_or_admin(current_user)

    if not can_manage_group(group_id, current_user, db_cursor):
        raise HTTPException(status_code=403, detail="Нет доступа к этой группе")

    # Информация о группе
    db_cursor.execute(
        """
        SELECT g.*, t.full_name as trainer_name
        FROM groups g
        LEFT JOIN trainers t ON g.trainer_id = t.id
        WHERE g.id = ?
        """,
        (group_id,)
    )
    group = db_cursor.fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")

    # Список учеников (активных)
    db_cursor.execute(
        """
        SELECT c.id, c.full_name, c.age, c.class_number, c.school_name,
               c.swimming_years, c.shift, e.enrolled_at
        FROM enrollments e
        JOIN children c ON e.child_id = c.id
        WHERE e.group_id = ? AND e.is_active = 1
        ORDER BY c.full_name
        """,
        (group_id,)
    )
    students = db_cursor.fetchall()

    # Расписание группы
    db_cursor.execute(
        """
        SELECT id, weekday, start_time, end_time, location, is_recurring, single_date
        FROM schedule
        WHERE group_id = ?
        ORDER BY weekday, start_time
        """,
        (group_id,)
    )
    schedule = db_cursor.fetchall()

    return templates.TemplateResponse(
        request,
        "group_details.html",
        {
            "request": request,
            "group": dict(group),
            "students": students,
            "schedule": schedule,
            "current_user": current_user,
            "group_id": group_id
        }
    )


# ---------- Управление учениками в группе ----------

# Страница добавления ученика (форма поиска по незачисленным детям)
@app.get("/trainer/group/{group_id}/add_student", response_class=HTMLResponse)
async def add_student_form(
    request: Request,
    group_id: int,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Форма для поиска и добавления ученика в группу."""
    require_trainer_or_admin(current_user)
    if not can_manage_group(group_id, current_user, db_cursor):
        raise HTTPException(status_code=403, detail="Нет доступа")

    # Список всех детей, которые ещё не зачислены в эту группу (или не зачислены никуда)
    db_cursor.execute(
        """
        SELECT c.id, c.full_name, c.age, c.class_number, c.school_name
        FROM children c
        WHERE c.id NOT IN (
            SELECT child_id FROM enrollments WHERE group_id = ? AND is_active = 1
        )
        ORDER BY c.full_name
        """,
        (group_id,)
    )
    available_children = db_cursor.fetchall()

    return templates.TemplateResponse(
        request,
        "add_student_to_group.html",
        {
            "request": request,
            "group_id": group_id,
            "children": available_children,
            "current_user": current_user
        }
    )

@app.post("/trainer/group/{group_id}/add_student")
async def add_student_submit(
    request: Request,
    group_id: int,
    child_id: Annotated[int, Form()],
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Добавляет ученика в группу."""
    require_trainer_or_admin(current_user)
    if not can_manage_group(group_id, current_user, db_cursor):
        raise HTTPException(status_code=403, detail="Нет доступа")

    # Проверяем, не зачислен ли уже
    db_cursor.execute(
        "SELECT id FROM enrollments WHERE child_id = ? AND group_id = ? AND is_active = 1",
        (child_id, group_id)
    )
    if db_cursor.fetchone():
        return RedirectResponse(url=f"/trainer/group/{group_id}?error=already_enrolled", status_code=303)

    # Добавляем запись
    db_cursor.execute(
        "INSERT INTO enrollments (child_id, group_id, enrolled_at) VALUES (?, ?, ?)",
        (child_id, group_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    db_cursor.connection.commit()
    return RedirectResponse(url=f"/trainer/group/{group_id}?success=added", status_code=303)

@app.post("/trainer/group/{group_id}/remove_student/{child_id}")
async def remove_student(
    request: Request,
    group_id: int,
    child_id: int,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Отчисляет (мягко удаляет) ученика из группы."""
    require_trainer_or_admin(current_user)
    if not can_manage_group(group_id, current_user, db_cursor):
        raise HTTPException(status_code=403, detail="Нет доступа")

    db_cursor.execute(
        "UPDATE enrollments SET is_active = 0 WHERE child_id = ? AND group_id = ?",
        (child_id, group_id)
    )
    db_cursor.connection.commit()
    return RedirectResponse(url=f"/trainer/group/{group_id}?success=removed", status_code=303)


# ---------- Редактирование данных ученика ----------
@app.get("/trainer/student/{child_id}/edit", response_class=HTMLResponse)
async def edit_student_form(
    request: Request,
    child_id: int,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """
    Редактирование данных ученика (только педагогические поля).
    Доступно тренеру, если ребёнок числится в группе этого тренера, либо админу.
    """
    require_trainer_or_admin(current_user)

    # Получаем данные ученика
    db_cursor.execute(
        """
        SELECT id, full_name, age, class_number, school_name,
               swimming_years, shift, desired_lessons_per_week
        FROM children
        WHERE id = ?
        """,
        (child_id,)
    )
    child = db_cursor.fetchone()
    if not child:
        raise HTTPException(status_code=404, detail="Ученик не найден")

    # Проверяем, что тренер имеет право (если не админ)
    if current_user["type"] != "admin":
        # Найдём группу, где числится этот ученик, и проверим, что тренер группы — текущий
        db_cursor.execute(
            """
            SELECT g.trainer_id
            FROM enrollments e
            JOIN groups g ON e.group_id = g.id
            WHERE e.child_id = ? AND e.is_active = 1
            """,
            (child_id,)
        )
        group = db_cursor.fetchone()
        if not group or group["trainer_id"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Нет прав на редактирование этого ученика")

    return templates.TemplateResponse(
        request,
        "edit_student.html",
        {
            "request": request,
            "child": dict(child),
            "current_user": current_user
        }
    )

@app.post("/trainer/student/{child_id}/edit")
async def edit_student_submit(
    request: Request,
    child_id: int,
    full_name: Annotated[str, Form()],
    age: Annotated[int, Form()],
    school_name: Annotated[str, Form()],
    swimming_years: Annotated[int, Form()],
    shift: Annotated[str, Form()],
    desired_lessons_per_week: Annotated[int, Form()],
    class_number: Annotated[Optional[int], Form()] = None,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Обновление данных ученика."""
    require_trainer_or_admin(current_user)

    # Проверка прав такая же, как в GET
    if current_user["type"] != "admin":
        db_cursor.execute(
            """
            SELECT g.trainer_id
            FROM enrollments e
            JOIN groups g ON e.group_id = g.id
            WHERE e.child_id = ? AND e.is_active = 1
            """,
            (child_id,)
        )
        group = db_cursor.fetchone()
        if not group or group["trainer_id"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Нет прав на редактирование")

    # Валидация
    if not (3 <= age <= 17):
        raise HTTPException(status_code=400, detail="Возраст должен быть от 3 до 17")
    if shift not in ("day", "evening"):
        shift = "day"
    if desired_lessons_per_week not in (1, 2, 3):
        desired_lessons_per_week = 2

    db_cursor.execute(
        """
        UPDATE children
        SET full_name = ?, age = ?, class_number = ?, school_name = ?,
            swimming_years = ?, shift = ?, desired_lessons_per_week = ?
        WHERE id = ?
        """,
        (full_name, age, class_number, school_name, swimming_years, shift, desired_lessons_per_week, child_id)
    )
    db_cursor.connection.commit()
    return RedirectResponse(url=f"/trainer/student/{child_id}/edit?success=updated", status_code=303)


# ---------- Журнал посещаемости ----------
@app.get("/trainer/group/{group_id}/attendance", response_class=HTMLResponse)
async def attendance_mark_form(
    request: Request,
    group_id: int,
    date_param: Optional[str] = None,  # дата в формате YYYY-MM-DD
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Форма для отметки посещаемости на выбранную дату."""
    require_trainer_or_admin(current_user)
    if not can_manage_group(group_id, current_user, db_cursor):
        raise HTTPException(status_code=403, detail="Нет доступа")

    # Если дата не задана, используем сегодняшнюю
    if not date_param:
        dt = date.today()
    else:
        try:
            dt = date.fromisoformat(date_param)
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат даты")

    # Список активных учеников группы
    db_cursor.execute(
        """
        SELECT c.id, c.full_name
        FROM enrollments e
        JOIN children c ON e.child_id = c.id
        WHERE e.group_id = ? AND e.is_active = 1
        ORDER BY c.full_name
        """,
        (group_id,)
    )
    students = db_cursor.fetchall()

    # Существующие отметки на эту дату
    attendance_map = {}
    for student in students:
        # Находим enrollment_id
        db_cursor.execute("SELECT id FROM enrollments WHERE child_id = ? AND group_id = ? AND is_active = 1", (student["id"], group_id))
        enrollment = db_cursor.fetchone()
        if enrollment:
            db_cursor.execute(
                "SELECT status FROM attendance WHERE enrollment_id = ? AND date = ?",
                (enrollment["id"], dt.isoformat())
            )
            row = db_cursor.fetchone()
            attendance_map[student["id"]] = row["status"] if row else None

    return templates.TemplateResponse(
        request,
        "attendance_mark.html",
        {
            "request": request,
            "group_id": group_id,
            "students": students,
            "date": dt,
            "attendance": attendance_map,
            "current_user": current_user
        }
    )


@app.post("/trainer/group/{group_id}/attendance")
async def attendance_mark_save(
    request: Request,
    group_id: int,
    date_str: Annotated[str, Form()],
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Сохранение отметок посещаемости."""
    require_trainer_or_admin(current_user)
    if not can_manage_group(group_id, current_user, db_cursor):
        raise HTTPException(status_code=403, detail="Нет доступа")

    form = await request.form()
    # Ожидается, что в форме будут поля вида "status_{child_id}" со значениями 'present', 'absent', 'sick', 'excused'
    for key, value in form.items():
        if key.startswith("status_"):
            child_id = int(key.split("_")[1])
            # Находим enrollment_id
            db_cursor.execute(
                "SELECT id FROM enrollments WHERE child_id = ? AND group_id = ? AND is_active = 1",
                (child_id, group_id)
            )
            enrollment = db_cursor.fetchone()
            if not enrollment:
                continue
            enrollment_id = enrollment["id"]
            # Проверяем, есть ли уже запись
            db_cursor.execute(
                "SELECT id FROM attendance WHERE enrollment_id = ? AND date = ?",
                (enrollment_id, date_str)
            )
            existing = db_cursor.fetchone()
            if existing:
                db_cursor.execute(
                    "UPDATE attendance SET status = ?, mark_time = ? WHERE id = ?",
                    (value, datetime.now().isoformat(), existing["id"])
                )
            else:
                db_cursor.execute(
                    "INSERT INTO attendance (enrollment_id, date, status, mark_time) VALUES (?, ?, ?, ?)",
                    (enrollment_id, date_str, value, datetime.now().isoformat())
                )
    db_cursor.connection.commit()
    return RedirectResponse(url=f"/trainer/group/{group_id}/attendance?date={date_str}&success=1", status_code=303)


# ---------- Управление расписанием группы ----------
@app.get("/trainer/group/{group_id}/schedule/edit", response_class=HTMLResponse)
async def edit_schedule_form(
    request: Request,
    group_id: int,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Форма для редактирования расписания: можно добавлять/удалять занятия."""
    require_trainer_or_admin(current_user)
    if not can_manage_group(group_id, current_user, db_cursor):
        raise HTTPException(status_code=403, detail="Нет доступа")

    # Получаем расписание группы
    db_cursor.execute(
        "SELECT id, weekday, start_time, end_time, location, is_recurring, single_date FROM schedule WHERE group_id = ?",
        (group_id,)
    )
    schedule = db_cursor.fetchall()

    return templates.TemplateResponse(
        request,
        "edit_schedule.html",
        {
            "request": request,
            "group_id": group_id,
            "schedule": schedule,
            "weekdays": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"],
            "current_user": current_user
        }
    )


@app.post("/trainer/group/{group_id}/schedule/add")
async def add_schedule_item(
    request: Request,
    group_id: int,
    weekday: Annotated[int, Form()],
    start_time: Annotated[str, Form()],
    end_time: Annotated[str, Form()],
    location: Annotated[str, Form()] = "",
    is_recurring: Annotated[bool, Form()] = True,
    single_date: Annotated[Optional[str], Form()] = None,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Добавляет занятие в расписание группы."""
    require_trainer_or_admin(current_user)
    if not can_manage_group(group_id, current_user, db_cursor):
        raise HTTPException(status_code=403, detail="Нет доступа")

    db_cursor.execute(
        """
        INSERT INTO schedule (group_id, weekday, start_time, end_time, location, is_recurring, single_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (group_id, weekday, start_time, end_time, location, is_recurring, single_date)
    )
    db_cursor.connection.commit()
    return RedirectResponse(url=f"/trainer/group/{group_id}/schedule/edit?success=added", status_code=303)


@app.post("/trainer/schedule/{schedule_id}/delete")
async def delete_schedule_item(
    request: Request,
    schedule_id: int,
    current_user = Depends(get_current_user),
    db_cursor = Depends(get_db)
):
    """Удаляет занятие из расписания."""
    # Сначала узнаем group_id
    db_cursor.execute("SELECT group_id FROM schedule WHERE id = ?", (schedule_id,))
    row = db_cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Занятие не найдено")
    group_id = row["group_id"]

    require_trainer_or_admin(current_user)
    if not can_manage_group(group_id, current_user, db_cursor):
        raise HTTPException(status_code=403, detail="Нет доступа")

    db_cursor.execute("DELETE FROM schedule WHERE id = ?", (schedule_id,))
    db_cursor.connection.commit()
    return RedirectResponse(url=f"/trainer/group/{group_id}/schedule/edit?success=deleted", status_code=303)