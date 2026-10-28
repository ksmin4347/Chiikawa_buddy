import sqlite3

SCHEMA_VERSION = 2


def migrate(connection: sqlite3.Connection, old_version: int) -> None:
    if old_version < 1:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS app_settings "
            "(setting_key TEXT PRIMARY KEY, setting_value TEXT NOT NULL)"
        )
    if old_version < 2:
        statements = [
            """CREATE TABLE categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                color TEXT NOT NULL)""",
            """CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                scheduled_date TEXT NOT NULL, start_time TEXT, due_at TEXT,
                priority INTEGER NOT NULL DEFAULT 1 CHECK(priority BETWEEN 0 AND 2),
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                completed INTEGER NOT NULL DEFAULT 0, recurrence TEXT,
                reminder_minutes INTEGER, timezone TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                start_at TEXT NOT NULL, end_at TEXT NOT NULL, all_day INTEGER NOT NULL DEFAULT 0,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                recurrence TEXT, reminder_minutes INTEGER, timezone TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
            """CREATE TABLE recurrence_exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
                event_id INTEGER REFERENCES calendar_events(id) ON DELETE CASCADE,
                original_key TEXT NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0,
                overrides TEXT,
                CHECK ((task_id IS NOT NULL) != (event_id IS NOT NULL)),
                UNIQUE(task_id, original_key), UNIQUE(event_id, original_key))""",
            """CREATE TABLE task_completions (
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                original_key TEXT NOT NULL, completed INTEGER NOT NULL,
                PRIMARY KEY(task_id, original_key))""",
            """CREATE TABLE notification_log (
                notification_key TEXT PRIMARY KEY, handled_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('shown', 'suppressed')))""",
            "CREATE INDEX tasks_date_idx ON tasks(scheduled_date)",
            "CREATE INDEX events_start_idx ON calendar_events(start_at)",
        ]
        for statement in statements:
            connection.execute(statement)
        connection.executemany(
            "INSERT INTO categories(name,color) VALUES (?,?)",
            [
                ("공부", "#4e8061"),
                ("일상", "#a16d37"),
                ("약속", "#526eab"),
            ],
        )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
