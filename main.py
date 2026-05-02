# main.py

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from database import db_instance
from init_db import create_tables, seed_test_data, ensure_tables_exist
from contextlib import asynccontextmanager


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


# ========== ЗАЯВКА ==========
#@app.get("")