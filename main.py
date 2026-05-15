# main.py

from fastapi import (
    FastAPI, Request, HTTPException, Depends, status,
    Form, UploadFile, File, Coockie)
from typing import Annotated, Optional
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import secrets
from database import db_instance, get_db
from init_db import create_tables, seed_test_data, ensure_tables_exist
from contextlib import asynccontextmanager
# Добавь после существующих импортов
from datetime import datetime, date, timedelta


# ========== ГЛАВНАЯ СТРАНИЦА ==========
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Главная страница"""
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


# ========== ДАШБОРД РОДИТЕЛЯ ==========
@app.get("/parent/dashboard", response_class=HTMLResponse)
async def parent_dashboard(request: Request):
    """Личный кабинет родителя"""
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in active_sessions:
        return RedirectResponse(url="/login", status_code=303)

    session = active_sessions[session_token]
    if session["user_type"] != "parent":
        return RedirectResponse(url="/", status_code=303)

    with get_db_cursor() as cursor:
        # Получаем данные родителя
        cursor.execute("SELECT * FROM parents WHERE id = ?", (session["user_id"],))
        parent = cursor.fetchone()

        # Получаем детей с информацией о группах и тренерах
        cursor.execute("""
            SELECT c.*, 
                   g.name as group_name,
                   t.full_name as trainer_name
            FROM children c
            LEFT JOIN enrollments e ON c.id = e.child_id AND e.is_active = 1
            LEFT JOIN groups g ON e.group_id = g.id
            LEFT JOIN trainers t ON g.trainer_id = t.id
            WHERE c.parent_id = ?
        """, (session["user_id"],))
        children = cursor.fetchall()

        # Проверяем наличие заявки
        cursor.execute("""
            SELECT * FROM applications 
            WHERE parent_phone = ? 
            ORDER BY created_at DESC LIMIT 1
        """, (parent["phone"],))
        application = cursor.fetchone()

    return templates.TemplateResponse(
        "parent_dashboard.html",
        {
            "request": request,
            "parent": parent,
            "children": children,
            "application": application,
            "current_month": date.today().strftime("%Y-%m")
        }
    )


# ========== ДАШБОРД ТРЕНЕРА ==========
@app.get("/coach/dashboard", response_class=HTMLResponse)
async def coach_dashboard(request: Request):
    """Панель тренера"""
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in active_sessions:
        return RedirectResponse(url="/login", status_code=303)

    session = active_sessions[session_token]
    if session["user_type"] != "trainer":
        return RedirectResponse(url="/", status_code=303)

    with get_db_cursor() as cursor:
        # Данные тренера
        cursor.execute("SELECT * FROM trainers WHERE id = ?", (session["user_id"],))
        trainer = cursor.fetchone()

        # Группы тренера с количеством учеников
        cursor.execute("""
            SELECT g.*, COUNT(e.id) as students_count
            FROM groups g
            LEFT JOIN enrollments e ON g.id = e.group_id AND e.is_active = 1
            WHERE g.trainer_id = ?
            GROUP BY g.id
        """, (session["user_id"],))
        groups = cursor.fetchall()

    return templates.TemplateResponse(
        "coach_dashboard.html",
        {
            "request": request,
            "trainer": trainer,
            "groups": groups,
            "today": date.today().isoformat()
        }
    )


# ========== API ДЛЯ ПОСЕЩАЕМОСТИ ==========
@app.get("/api/attendance/{group_id}/{date}")
async def get_attendance(group_id: int, date_str: str, request: Request, db_cursor=Depends(get_db)):
    """Получить посещаемость группы за дату"""
    # Проверка авторизации
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in active_sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    db_cursor.execute("""
        SELECT c.id as child_id, c.full_name, 
               e.id as enrollment_id,
               a.status,
               a.mark_time
        FROM children c
        JOIN enrollments e ON c.id = e.child_id
        LEFT JOIN attendance a ON e.id = a.enrollment_id AND a.date = ?
        WHERE e.group_id = ? AND e.is_active = 1
    """, (target_date, group_id))

    attendance = db_cursor.fetchall()
    return list(attendance)


@app.post("/api/attendance/save")
async def save_attendance(request: Request, db_cursor=Depends(get_db)):
    """Сохранить посещаемость"""
    session_token = request.cookies.get("session_token")
    if not session_token or session_token not in active_sessions:
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = await request.json()

    for item in data:
        db_cursor.execute("""
            INSERT INTO attendance (enrollment_id, date, status, mark_time)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(enrollment_id, date) DO UPDATE SET
                status = excluded.status,
                mark_time = excluded.mark_time
        """, (item["enrollment_id"], item["date"], item["status"], datetime.now()))

    return {"success": True}


# ========== API ДЛЯ ЗАЯВОК ==========
@app.post("/api/application/submit")
async def submit_application(
        parent_full_name: str = Form(...),
        parent_phone: str = Form(...),
        parent_email: Optional[str] = Form(None),
        vk_id: Optional[str] = Form(None),
        child_full_name: str = Form(...),

# Хранилище активных сессий: {token: {"user_id": int, "user_type": str, "login": str}}
active_sessions = {}

def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


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
            count = cursor.fetchone()[0]
            if count == 0:
                print("Данные отсутствуют. Заполнение тестовыми данными...")
                seed_test_data()
            else:
                print("Данные уже существуют. Пропускаем инициализацию.")

    print("Приложение готово к работе")

    yield  # Здесь работает само приложение

    # Завершение работы
    print("Остановка приложения, закрытие соединения с БД...")
    db_instance.close()
    print("Соединение закрыто")


# Инициализация FastAPI
app = FastAPI(
    title="pool_crm",
    description="SRM для бассейна",
    version="1.0.0",
    lifespan=lifespan
)

# Подключение статики и шаблонов
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ========== СТРАНИЦА ВХОДА ==========
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """
    Показывает страницу входа в систему
    """

    return templates.TeemplateResponse(
        request, # В новых версиях обязательно первым параметром указывать request
        "login.html",
        {"request": request, "title": "Вход в систему"}
    )

@app.post("/login")
async def login(
        request: Request,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
        db_cursor = Depends(get_db)
):
    """
    Обрабатывает форму входа
    """

    # Ищем тренера в базе данных
    db_cursor.execute("SELECT id, login, password_hash, 'trainer' as type FROM trainers WHERE login = ?", (username,))
    user = db_cursor.fetchone()

    # Если не тренер, ищем родителя по телефону
    if not user:
        db_cursor.execute("SELECT id, phone, password_hash, 'parent' as type FROM parents WHERE phone = ?", (username,))
        user = db_cursor.fetchone()

    # Проверяем пароль (простое сравнение строк)
    if user and user["password_hash"] == password:
        token = secrets.token_urlsafe(32)
        active_sessions[token] = {"user_id": user["id"], "user_type": user["type"]}
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("session_token", token, httponly=True)
        return response

    return templates.TemplateResponse(
        request,
        "login.html",
        {"request": request, "error": "Неверный логин/пароль"}
    )