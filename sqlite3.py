"""
SQLite-compatible facade backed by PostgreSQL.

The existing Filamanager application was written against Python's sqlite3 API.
On Render, local SQLite files are ephemeral, so this module preserves the small
sqlite3 API surface used by app.py while storing all data in the PostgreSQL
DATABASE_URL configured in the environment.
"""

import os
import re

import psycopg2
from psycopg2.extras import DictCursor


# app.py assigns `conn.row_factory = sqlite3.Row`. PostgreSQL DictCursor already
# supplies mapping-style rows, so Row is only a compatibility marker.
class Row:
    pass


def _replace_qmark_placeholders(sql):
    """Convert SQLite ? placeholders to psycopg2 %s, outside quoted strings."""
    out = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'" and not in_double:
            # SQL escapes a single quote by doubling it.
            if in_single and i + 1 < len(sql) and sql[i + 1] == "'":
                out.extend(["'", "'"])
                i += 2
                continue
            in_single = not in_single
            out.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
        elif ch == '?' and not in_single and not in_double:
            out.append('%s')
        else:
            out.append(ch)
        i += 1
    return ''.join(out)


def _translate_sql(sql):
    """Translate the SQLite-specific SQL used by app.py to PostgreSQL."""
    original = sql
    sql = sql.strip()

    # SQLite autoincrementing primary keys -> PostgreSQL sequence-backed keys.
    sql = re.sub(
        r'\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b',
        'SERIAL PRIMARY KEY',
        sql,
        flags=re.IGNORECASE,
    )

    # SQLite INSERT OR IGNORE -> PostgreSQL ON CONFLICT DO NOTHING.
    insert_or_ignore = bool(re.search(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b', sql, re.IGNORECASE))
    if insert_or_ignore:
        sql = re.sub(r'\bINSERT\s+OR\s+IGNORE\s+INTO\b', 'INSERT INTO', sql, flags=re.IGNORECASE)
        if not re.search(r'\bON\s+CONFLICT\b', sql, re.IGNORECASE):
            sql = sql.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'

    # SQLite date formatting used by the dashboard.
    sql = re.sub(
        r'''strftime\(\s*["']%Y-%m["']\s*,\s*completed_at\s*\)''',
        "TO_CHAR(completed_at, 'YYYY-MM')",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r'''strftime\(\s*["']%Y-%m["']\s*,\s*["']now["']\s*\)''',
        "TO_CHAR(CURRENT_TIMESTAMP, 'YYYY-MM')",
        sql,
        flags=re.IGNORECASE,
    )

    # A few common SQLite functions are harmlessly mapped for compatibility.
    sql = re.sub(r'\bIFNULL\s*\(', 'COALESCE(', sql, flags=re.IGNORECASE)
    sql = re.sub(r'''date\(\s*["']now["']\s*\)''', 'CURRENT_DATE', sql, flags=re.IGNORECASE)
    sql = re.sub(r'''datetime\(\s*["']now["']\s*\)''', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
    sql = re.sub(
        r'''date\(\s*["']now["']\s*,\s*["']-(\d+)\s+days?["']\s*\)''',
        r"(CURRENT_DATE - INTERVAL '\1 days')",
        sql,
        flags=re.IGNORECASE,
    )

    # SQLite accepts double-quoted string literals in comparisons. PostgreSQL
    # reserves double quotes for identifiers, so normalize the pattern used by
    # this app (for example: status = "available").
    sql = re.sub(r'''([=<>]\s*)"([^"\n]+)"''', lambda m: m.group(1) + "'" + m.group(2).replace("'", "''") + "'", sql)

    sql = _replace_qmark_placeholders(sql)
    return sql, original


class Cursor:
    def __init__(self, connection, raw_cursor):
        self._connection = connection
        self._cursor = raw_cursor

    def execute(self, sql, parameters=None):
        translated, original = _translate_sql(sql)
        parameters = () if parameters is None else parameters

        # If an INSERT explicitly supplies id, remember the table so its SERIAL
        # sequence can be advanced before commit (admin/cost_settings seed rows).
        match = re.search(r'\bINSERT(?:\s+OR\s+IGNORE)?\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*id\s*,', original, re.IGNORECASE)
        if match:
            self._connection._sequence_tables.add(match.group(1))

        if parameters:
            self._cursor.execute(translated, parameters)
        else:
            self._cursor.execute(translated)
        return self

    def executemany(self, sql, seq_of_parameters):
        translated, _ = _translate_sql(sql)
        self._cursor.executemany(translated, seq_of_parameters)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size) if size is not None else self._cursor.fetchmany()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    @property
    def lastrowid(self):
        # app.py does not rely on lastrowid; expose a compatible attribute.
        return None

    def close(self):
        return self._cursor.close()

    def __iter__(self):
        return iter(self._cursor)


class Connection:
    def __init__(self, raw_connection):
        self._connection = raw_connection
        self._sequence_tables = set()
        self._row_factory = Row

    @property
    def row_factory(self):
        return self._row_factory

    @row_factory.setter
    def row_factory(self, value):
        # DictCursor is already configured globally on the PostgreSQL connection.
        self._row_factory = value

    def cursor(self):
        return Cursor(self, self._connection.cursor())

    def execute(self, sql, parameters=None):
        cur = self.cursor()
        return cur.execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters):
        cur = self.cursor()
        return cur.executemany(sql, seq_of_parameters)

    def _sync_sequences(self):
        if not self._sequence_tables:
            return
        cur = self._connection.cursor()
        try:
            for table in sorted(self._sequence_tables):
                # Table names originate from static application SQL and are also
                # restricted by the parser above to safe identifier characters.
                cur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
                row = cur.fetchone()
                sequence_name = row[0] if row else None
                if sequence_name:
                    cur.execute(f'SELECT COALESCE(MAX(id), 0) FROM "{table}"')
                    max_id = cur.fetchone()[0]
                    if max_id and max_id > 0:
                        cur.execute('SELECT setval(%s, %s, true)', (sequence_name, max_id))
        finally:
            cur.close()
        self._sequence_tables.clear()

    def commit(self):
        self._sync_sequences()
        return self._connection.commit()

    def rollback(self):
        self._sequence_tables.clear()
        return self._connection.rollback()

    def close(self):
        return self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False


def connect(database=None, timeout=None, *args, **kwargs):
    """sqlite3.connect-compatible entry point using Render's DATABASE_URL."""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise RuntimeError(
            'DATABASE_URL is not configured. Set the Render PostgreSQL internal '
            'database URL as the DATABASE_URL environment variable.'
        )

    raw = psycopg2.connect(database_url, cursor_factory=DictCursor)
    return Connection(raw)
