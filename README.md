# Система учёта посетителей бассейна
## 1. Запуск приложения
### Для запуска приложения введите в окне терминала команду: 
### uvicorn main:app --reload
### База данных создастся автоматически
## 2. Библиотеки
### Установка библиотек тремя командами:
### pip install fastapi uvicorn
### pip install jinja2
### pip install python-multipart

# Database (Удалов Арсений)
## init_db.py
## Используется для создания таблиц и заполнения их тестовыми данными
### 1. Библиотеки, которые мы импортируем:
* import sqlite3 
* import os 
* from datetime import datetime, time, date, timedelta
* from database import db_instance, get_db_cursor, DATABASE_PATH (файл database)
### 2. Функции:
* table_exists() - Проверяет, существует ли таблица в базе данных SQLite
* create_tables() - Создаёт все таблицы:
* ensure_tables_exist() - Проверяет существование таблиц и создаёт их при необходимости
* seed_test_data() - Заполнение тестовыми данными для разработки
* drop_all_tables() - Удаляет ВСЕ таблицы из базы данных (без пересоздания)
* reset_database() - Удаляет все таблицы и создаёт их заново с тестовыми данными
* recreate_database() - Полностью пересоздаёт базу данных
* reset_database_safe() - Безопасная версия сброса с подтверждением
* show_tables() - Показать список всех таблиц в базе данных
* get_database_info() - Получить подробную информацию о базе данных
* create_full_database() - Создаёт полную базу данных с таблицами и тестовыми данными
### 3. Таблицы, которые мы создаём (в правильном порядке):
* Таблица родителей (parents)
* Таблица детей (children)
* Таблица тренеров (trainers)
* Таблица групп (groups)
* Таблица зачислений (enrollments)
* Таблица расписания (schedule)
* Таблица посещаемости(attendance)
* Таблица заявок (applications)
* Таблица логов администратора (admin_logs)
* Таблица уведомлений (notifications)
### 4. Самостоятельный запуск init_db
1) if len(sys.argv) < 2: Если аргументов меньше 2 (то есть нет команды)
2) Выводим справку (help)
3) sys.exit(0) Выходим из программы с кодом 0 (успешное завершение)
4) command = sys.argv[1] Берём первый аргумент (команду)
5) if command == "create": create_tables() Создание таблиц 
6) elif command == "seed": seed_test_data() Заполнение тестовыми данными 
7) elif command == "reset": reset_database() Полный сброс (удаление + создание + заполнение)
8) elif command == "drop": drop_all_tables() Удаление всех таблиц 
9) elif command == "recreate": recreate_database() Пересоздание с удалением файла 
10) elif command == "show": show_tables() Показать список таблиц 
11) elif command == "info": get_database_info() Показать подробную информацию о БД 
12) elif command == "full": create_full_database() Создать полную БД (таблицы + данные)
13) else: Если команда не распознана 
14) print(f"❌ Unknown command: {command}")
15) print("Use: create, seed, reset, drop, recreate, show, info, full")
### 5. Индексы для производительности:
* Индекс на внешний ключ родителя в таблице children
* Индекс на ID ребёнка в таблице зачислений 
* Индекс на ID группы в таблице зачислений 
* Индекс на ID зачисления в таблице посещаемости 
* Индекс на дату в таблице посещаемости 
* Индекс на статус в таблице заявок 
* Индекс на телефон в таблице заявок 
* Индекс на группу в таблице расписания 
* Индекс на статус в таблице уведомлений 
* Индекс на тренера в таблице групп
## database.py
## Управляет подключением к базе данных
### 1. Библиотеки, которые мы импортируем:
* import sqlite3 
* from contextlib import contextmanager 
* from fastapi import FastAPI, Depends, HTTPException
### 2. Класс Database 
1) def __init__(): Класс для управления подключением к SQLite
2) get_connection(): Создаёт соединение с SQLite при первом запросе
3) close(): Закрыть соединение с БД
### 3. Функции:
* get_db_cursor() - Автоматически управляет транзакциями
* get_db() - Используется в эндпоинтах для получения курсора
* init_database() - Функция для инициализации БД (будет вызвана при старте)