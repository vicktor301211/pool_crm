# init_db.py
import sqlite3
import os
from database import db_instance, get_db_cursor, DATABASE_PATH
from datetime import datetime, time, date, timedelta


def table_exists(cursor, table_name):
    """Проверяет, существует ли таблица в базе данных"""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    )
    return cursor.fetchone() is not None


def create_tables():
    """Создание всех таблиц согласно схеме"""

    with get_db_cursor() as cursor:
        # 1. Таблица родителей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS parents ( 
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name VARCHAR(255) NOT NULL,
                phone VARCHAR(20) NOT NULL UNIQUE,
                email VARCHAR(255),
                vk_id VARCHAR(100) UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Таблица детей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS children (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER NOT NULL,
                full_name VARCHAR(255) NOT NULL,
                age INTEGER CHECK (age BETWEEN 3 AND 17),
                class_number INTEGER CHECK (class_number BETWEEN 0 AND 11 OR class_number IS NULL),
                school_name VARCHAR(255),
                swimming_years INTEGER DEFAULT 1,
                shift VARCHAR(10) CHECK (shift IN ('day', 'evening')),
                desired_lessons_per_week INTEGER CHECK (desired_lessons_per_week IN (1,2,3)),
                FOREIGN KEY (parent_id) REFERENCES parents(id) ON DELETE CASCADE
            )
        """)

        # 3. Таблица тренеров
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trainers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name VARCHAR(255) NOT NULL,
                phone VARCHAR(20),
                email VARCHAR(255),
                login VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                specialization TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 4. Таблица групп
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                trainer_id INTEGER,
                min_age INTEGER DEFAULT 3,
                max_age INTEGER DEFAULT 17,
                swimming_year INTEGER DEFAULT 1,
                max_students INTEGER DEFAULT 15,
                shift VARCHAR(10) CHECK (shift IN ('day', 'evening')),
                is_active BOOLEAN DEFAULT 1,
                FOREIGN KEY (trainer_id) REFERENCES trainers(id) ON DELETE SET NULL
            )
        """)

        # 5. Таблица зачислений
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enrollments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                UNIQUE(child_id, group_id),
                FOREIGN KEY (child_id) REFERENCES children(id),
                FOREIGN KEY (group_id) REFERENCES groups(id)
            )
        """)

        # 6. Таблица расписания
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
                start_time TIME NOT NULL,
                end_time TIME NOT NULL,
                location VARCHAR(100),
                is_recurring BOOLEAN DEFAULT 1,
                single_date DATE,
                FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
            )
        """)

        # 7. Таблица посещаемости
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                enrollment_id INTEGER NOT NULL,
                date DATE NOT NULL,
                status VARCHAR(20) CHECK (status IN ('present', 'absent', 'sick', 'excused')),
                mark_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (enrollment_id) REFERENCES enrollments(id) ON DELETE CASCADE,
                UNIQUE(enrollment_id, date)
            )
        """)

        # 8. Таблица заявок
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_full_name VARCHAR(255) NOT NULL,
                parent_phone VARCHAR(20) NOT NULL,
                parent_email VARCHAR(255),
                child_full_name VARCHAR(255) NOT NULL,
                child_age INTEGER NOT NULL,
                child_class INTEGER,
                school_name VARCHAR(255),
                swimming_years INTEGER DEFAULT 1,
                shift VARCHAR(10) CHECK (shift IN ('day', 'evening')),
                desired_lessons_per_week INTEGER,
                status VARCHAR(20) DEFAULT 'new' CHECK (status IN ('new', 'processing', 'approved', 'rejected')),
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                processed_by INTEGER,
                FOREIGN KEY (processed_by) REFERENCES trainers(id)
            )
        """)

        # 9. Таблица логов администратора
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER NOT NULL,
                action VARCHAR(255) NOT NULL,
                entity_type VARCHAR(50),
                entity_id INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES trainers(id)
            )
        """)

        # 10. Таблица уведомлений
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_type VARCHAR(20) CHECK (user_type IN ('parent', 'trainer')),
                type VARCHAR(50) CHECK (type IN ('email', 'sms', 'vk', 'system')),
                title VARCHAR(255),
                message TEXT,
                status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
                sent_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Создание индексов для производительности
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_children_parent ON children(parent_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_enrollments_child ON enrollments(child_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_enrollments_group ON enrollments(group_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_enrollment ON attendance(enrollment_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_applications_phone ON applications(parent_phone)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_schedule_group ON schedule(group_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_groups_trainer ON groups(trainer_id)")

        print("✅ All tables created successfully")


def ensure_tables_exist():
    """Проверяет существование таблиц и создаёт их при необходимости"""
    with get_db_cursor() as cursor:
        if not table_exists(cursor, 'trainers'):
            print("📋 Tables not found, creating them first...")
            create_tables()
            return True
    return False


def seed_test_data():
    """Заполнение тестовыми данными для разработки"""

    # Проверяем, существуют ли таблицы
    ensure_tables_exist()

    with get_db_cursor() as cursor:
        # Проверяем, есть ли уже данные
        try:
            cursor.execute("SELECT COUNT(*) FROM trainers")
            count = cursor.fetchone()[0]
            if count > 0:
                print("📊 Test data already exists, skipping seed")
                return
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                print("❌ Tables still don't exist, cannot seed data")
                print("   Please run 'create_tables()' first or use 'reset_database()'")
                return
            raise e

        print("🌱 Seeding test data...")

        # Хеш пароля для тестовых пользователей (пароль: "password123")
        # В реальном проекте используйте bcrypt!
        test_password_hash = "test_hash_replace_with_bcrypt"

        # 1. Создаём тренеров
        trainers_data = [
            ("Анна Иванова", "+79001234567", "anna@swim.ru", "anna.trainer", test_password_hash,
             "Детское плавание, начальная подготовка"),
            ("Михаил Петров", "+79007654321", "mikhail@swim.ru", "mikhail.trainer", test_password_hash,
             "Спортивное плавание, старшие группы"),
            ("Елена Смирнова", "+79009998877", "elena@swim.ru", "elena.trainer", test_password_hash,
             "Оздоровительное плавание, малыши"),
        ]

        cursor.executemany("""
            INSERT INTO trainers (full_name, phone, email, login, password_hash, specialization)
            VALUES (?, ?, ?, ?, ?, ?)
        """, trainers_data)

        # 2. Создаём группы
        groups_data = [
            ("Дельфинчики (3-5 лет)", 1, 3, 5, 1, 10, "day"),
            ("Рыбки (6-8 лет)", 1, 6, 8, 1, 12, "day"),
            ("Спортивная (9-12 лет)", 2, 9, 12, 2, 15, "evening"),
            ("Продвинутая (13-17 лет)", 2, 13, 17, 3, 15, "evening"),
            ("Оздоровительная (7-10 лет)", 3, 7, 10, 1, 12, "day"),
        ]

        cursor.executemany("""
            INSERT INTO groups (name, trainer_id, min_age, max_age, swimming_year, max_students, shift)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, groups_data)

        # 3. Создаём родителей
        parents_data = [
            ("Сергей Петров", "+79123456789", "sergey@example.com", None),
            ("Ольга Сидорова", "+79234567890", "olga@example.com", None),
            ("Дмитрий Козлов", "+79345678901", "dmitry@example.com", None),
        ]

        cursor.executemany("""
            INSERT INTO parents (full_name, phone, email, vk_id)
            VALUES (?, ?, ?, ?)
        """, parents_data)

        # 4. Создаём детей
        children_data = [
            (1, "Алексей Петров", 7, 1, "Школа №1", 1, "day", 2),
            (1, "Мария Петрова", 5, 0, "Детский сад №5", 1, "day", 2),
            (2, "Екатерина Сидорова", 10, 3, "Школа №2", 2, "evening", 3),
            (3, "Иван Козлов", 14, 7, "Школа №3", 3, "evening", 2),
        ]

        cursor.executemany("""
            INSERT INTO children (parent_id, full_name, age, class_number, school_name, swimming_years, shift, desired_lessons_per_week)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, children_data)

        # 5. Зачисляем детей в группы
        enrollments_data = [
            (1, 2),  # Алексей Петров -> Рыбки
            (2, 1),  # Мария Петрова -> Дельфинчики
            (3, 3),  # Екатерина Сидорова -> Спортивная
            (4, 4),  # Иван Козлов -> Продвинутая
        ]

        cursor.executemany("""
            INSERT INTO enrollments (child_id, group_id)
            VALUES (?, ?)
        """, enrollments_data)

        # 6. Добавляем расписание
        schedule_data = [
            (1, 0, "10:00", "11:00", "Дорожка 1", 1, None),  # ПН, Дельфинчики
            (1, 2, "10:00", "11:00", "Дорожка 1", 1, None),  # СР, Дельфинчики
            (2, 0, "11:30", "12:30", "Дорожка 2", 1, None),  # ПН, Рыбки
            (2, 3, "11:30", "12:30", "Дорожка 2", 1, None),  # ЧТ, Рыбки
            (3, 1, "18:00", "19:30", "Дорожка 3", 1, None),  # ВТ, Спортивная
            (3, 4, "18:00", "19:30", "Дорожка 3", 1, None),  # ПТ, Спортивная
            (4, 1, "19:30", "21:00", "Дорожка 4", 1, None),  # ВТ, Продвинутая
            (4, 4, "19:30", "21:00", "Дорожка 4", 1, None),  # ПТ, Продвинутая
            (5, 0, "15:00", "16:00", "Дорожка 1", 1, None),  # ПН, Оздоровительная
            (5, 3, "15:00", "16:00", "Дорожка 1", 1, None),  # ЧТ, Оздоровительная
        ]

        cursor.executemany("""
            INSERT INTO schedule (group_id, weekday, start_time, end_time, location, is_recurring, single_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, schedule_data)

        # 7. Добавляем посещаемость за последнюю неделю
        attendance_data = []
        today = date.today()
        for i, enrollment in enumerate([(1, 2), (2, 1), (3, 3), (4, 4)], start=1):
            child_id, group_id = enrollment
            enrollment_id = i

            # Последние 3 занятия
            for days_ago in [1, 3, 5]:  # вчера, 3 дня назад, 5 дней назад
                d = today - timedelta(days=days_ago)
                status = "present" if days_ago != 5 else "absent"  # для примера
                attendance_data.append((enrollment_id, d, status))

        cursor.executemany("""
            INSERT INTO attendance (enrollment_id, date, status)
            VALUES (?, ?, ?)
        """, attendance_data)

        # 8. Добавляем тестовые заявки
        applications_data = [
            ("Нина Соколова", "+79991112233", "nina@example.com", "Артём Соколов", 8, 2, "Школа №4", 1, "day", 2, "new",
             None, None, None),
            (
                "Виктор Морозов", "+79885556677", None, "Дарья Морозова", 6, 0, "Школа №5", 1, "day", 2, "processing",
                None,
                None, None),
        ]

        cursor.executemany("""
            INSERT INTO applications (parent_full_name, parent_phone, parent_email, child_full_name, child_age, child_class, school_name, swimming_years, shift, desired_lessons_per_week, status, rejection_reason, processed_at, processed_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, applications_data)

        print("✅ Test data seeded successfully")
        print(f"📊 Statistics:")
        print(f"   - Trainers: {cursor.execute('SELECT COUNT(*) FROM trainers').fetchone()[0]}")
        print(f"   - Groups: {cursor.execute('SELECT COUNT(*) FROM groups').fetchone()[0]}")
        print(f"   - Parents: {cursor.execute('SELECT COUNT(*) FROM parents').fetchone()[0]}")
        print(f"   - Children: {cursor.execute('SELECT COUNT(*) FROM children').fetchone()[0]}")
        print(f"   - Enrollments: {cursor.execute('SELECT COUNT(*) FROM enrollments').fetchone()[0]}")


def drop_all_tables():
    """
    Удаляет ВСЕ таблицы из базы данных (без пересоздания)
    Полезно для чистого сброса перед миграциями
    """
    with get_db_cursor() as cursor:
        # Получаем список всех таблиц (исключая системные)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        tables = cursor.fetchall()

        if not tables:
            print("ℹ️ No tables found to drop")
            return

        # Отключаем проверку внешних ключей временно
        cursor.execute("PRAGMA foreign_keys = OFF")

        # Удаляем каждую таблицу
        for table in tables:
            table_name = table[0]
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
            print(f"   Dropped table: {table_name}")

        # Включаем проверку внешних ключей обратно
        cursor.execute("PRAGMA foreign_keys = ON")

    print(f"✅ Dropped {len(tables)} tables successfully")


def reset_database():
    """
    ПОЛНЫЙ СБРОС БАЗЫ ДАННЫХ (только для разработки!)
    Удаляет все таблицы и создаёт их заново с тестовыми данными
    """
    print("🔄 Starting database reset...")

    # Удаляем все таблицы
    drop_all_tables()

    # Пересоздаём таблицы и заполняем тестовыми данными
    create_tables()
    seed_test_data()

    print("✅ Database reset completed successfully!")


def recreate_database():
    """
    Полностью пересоздаёт базу данных:
    1. Закрывает существующее соединение
    2. Удаляет файл БД
    3. Создаёт всё заново
    """
    import os
    from database import db_instance, DATABASE_PATH

    print("🔄 Recreating database from scratch...")

    # Закрываем текущее соединение, если оно открыто
    db_instance.close()

    # Удаляем файл базы данных
    if os.path.exists(DATABASE_PATH):
        os.remove(DATABASE_PATH)
        print(f"🗑️ Removed database file: {DATABASE_PATH}")

    # Создаём таблицы и заполняем данными
    create_tables()
    seed_test_data()

    print("✅ Database recreated from scratch!")


def reset_database_safe():
    """
    Безопасная версия сброса с подтверждением
    """
    response = input("⚠️ WARNING: This will delete ALL data! Type 'yes' to continue: ")
    if response.lower() == 'yes':
        reset_database()
        print("✅ Database reset completed!")
    else:
        print("❌ Reset cancelled")


def show_tables():
    """Показать список всех таблиц в базе данных"""
    with get_db_cursor() as cursor:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tables = cursor.fetchall()

        if not tables:
            print("ℹ️ No tables found")
            return

        print("\n📋 Tables in database:")
        print("-" * 30)
        for table in tables:
            # Получаем количество записей в таблице
            cursor.execute(f"SELECT COUNT(*) FROM {table[0]}")
            count = cursor.fetchone()[0]
            print(f"   {table[0]}: {count} records")
        print("-" * 30)


def get_database_info():
    """Получить подробную информацию о базе данных"""
    import os
    from database import DATABASE_PATH

    print("\n📊 Database Information:")
    print("=" * 40)

    # Проверяем существует ли файл БД
    if os.path.exists(DATABASE_PATH):
        size = os.path.getsize(DATABASE_PATH)
        print(f"📁 File: {DATABASE_PATH}")
        print(f"💾 Size: {size} bytes ({size / 1024:.2f} KB)")
    else:
        print(f"❌ Database file not found: {DATABASE_PATH}")
        return

    # Показываем таблицы
    show_tables()

    print(f"\n🔧 SQLite version: {sqlite3.sqlite_version}")
    print("=" * 40)


def create_full_database():
    """
    Создаёт полную базу данных с таблицами и тестовыми данными
    (удобная функция для быстрого старта)
    """
    print("🚀 Creating full database...")
    create_tables()
    seed_test_data()
    print("✅ Full database created successfully!")


# Если запускаем файл напрямую
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("\n📚 Database Management Script")
        print("=" * 40)
        print("Usage:")
        print("  python init_db.py create     - Create tables")
        print("  python init_db.py seed       - Seed test data (auto-creates tables if needed)")
        print("  python init_db.py reset      - Reset database (drop + create + seed)")
        print("  python init_db.py drop       - Drop all tables")
        print("  python init_db.py recreate   - Recreate database from scratch")
        print("  python init_db.py show       - Show all tables")
        print("  python init_db.py info       - Show database information")
        print("  python init_db.py full       - Create full database (tables + data)")
        print("=" * 40)
        sys.exit(0)

    command = sys.argv[1]

    if command == "create":
        create_tables()
    elif command == "seed":
        seed_test_data()
    elif command == "reset":
        reset_database()
    elif command == "drop":
        drop_all_tables()
    elif command == "recreate":
        recreate_database()
    elif command == "show":
        show_tables()
    elif command == "info":
        get_database_info()
    elif command == "full":
        create_full_database()
    else:
        print(f"❌ Unknown command: {command}")
        print("Use: create, seed, reset, drop, recreate, show, info, full")