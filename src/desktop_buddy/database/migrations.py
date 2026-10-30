import sqlite3

SCHEMA_VERSION = 4


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
    if old_version < 3:
        statements = [
            """CREATE TABLE focus_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK(kind IN ('focus','short_break','long_break')),
                planned_seconds REAL NOT NULL CHECK(planned_seconds > 0),
                started_at TEXT NOT NULL, ended_at TEXT,
                active_seconds REAL NOT NULL DEFAULT 0 CHECK(active_seconds >= 0),
                paused_seconds REAL NOT NULL DEFAULT 0 CHECK(paused_seconds >= 0),
                completed INTEGER NOT NULL DEFAULT 0, interrupted INTEGER NOT NULL DEFAULT 0,
                category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
                category_name TEXT NOT NULL, category_color TEXT NOT NULL,
                task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                task_key TEXT, task_title TEXT NOT NULL, exit_reason TEXT NOT NULL DEFAULT '')""",
            """CREATE TABLE focus_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES focus_sessions(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
                elapsed_seconds REAL NOT NULL CHECK(elapsed_seconds >= 0))""",
            """CREATE TABLE timer_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                payload TEXT NOT NULL)""",
            "CREATE INDEX focus_segments_dates_idx ON focus_segments(started_at,ended_at)",
            "CREATE INDEX focus_sessions_end_idx ON focus_sessions(kind,ended_at)",
        ]
        for statement in statements:
            connection.execute(statement)
    if old_version < 4:
        connection.execute(
            "ALTER TABLE focus_sessions ADD COLUMN recorded INTEGER NOT NULL DEFAULT 1"
        )
        connection.execute("""CREATE TABLE rest_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT, start_date TEXT NOT NULL,
            end_date TEXT NOT NULL CHECK(end_date >= start_date))""")
        connection.execute("""CREATE TABLE companion_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), last_seen_at TEXT NOT NULL,
            clock_warning INTEGER NOT NULL DEFAULT 0)""")
        connection.execute("""CREATE TABLE companion_messages (
            kind TEXT NOT NULL, local_date TEXT NOT NULL, PRIMARY KEY(kind,local_date))""")
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
