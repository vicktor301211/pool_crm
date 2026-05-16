# database.py
import sqlite3
from contextlib import contextmanager
from fastapi import FastAPI, Depends, HTTPException

DATABASE_PATH = "swim_crm.db"  # Файл базы данных

class Database:
    # Класс для управления подключением к SQLite
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path  # Сохраняем путь к файлу БД в атрибуте объекта
        self._connection = None  # Инициализируем соединение как None (соединения пока нет)

    def get_connection(self): # Создаёт соединение с SQLite при первом запросе
        if self._connection is None:  # ПРОВЕРКА: Есть ли уже соединение?
            self._connection = sqlite3.connect(  # СОЗДАЕМ НОВОЕ СОЕДИНЕНИЕ
                self.db_path,  # Путь к файлу БД
                check_same_thread=False,  # Разрешаем использование в разных потоках
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES  #Преобразование типов данных
            )
            # Включаем поддержку внешних ключей (очень важно!)
            self._connection.execute("PRAGMA foreign_keys = ON")
            # Возвращаем строки как словари для удобства
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self):
        #Закрыть соединение с БД
        if self._connection is not None:
            self._connection.close()  # Закрывает соединение с БД
            self._connection = None  # Обнуляем переменную

# Глобальный экземпляр БД
db_instance = Database()

@contextmanager
def get_db_cursor():
    #Автоматически управляет транзакциями.
    conn = db_instance.get_connection()  # Получаем соединение
    cursor = conn.cursor()  # Создаем курсор
    try:
        yield cursor
        conn.commit()  # Автоматический коммит при успехе
    except Exception as e:
        conn.rollback()  # Откат при ошибке
        raise e
    finally:
        cursor.close()

def get_db():
    #Используется в эндпоинтах для получения курсора.
    with get_db_cursor() as cursor:
        yield cursor

# Функция для инициализации БД (будет вызвана при старте)
def init_database(app: FastAPI):
    from init_db import create_tables, seed_test_data

    @app.on_event("startup")
    async def startup():
        create_tables()
        seed_test_data()
        print("✅ Database initialized successfully")

    @app.on_event("shutdown")
    async def shutdown():
        db_instance.close()
        print("👋 Database connection closed")