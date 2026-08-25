import os
from pathlib import Path

import psycopg2

DATABASE_URL = os.getenv('DATABASE_URL')
MIGRATIONS_DIR = Path(__file__).with_name('migrations')


def register_runtime_extensions():
    """Register runtime blueprints before the app starts serving requests."""
    from app import app
    from stock_safety import stock_safety_bp
    from multicolor_stock import multicolor_stock_bp
    if stock_safety_bp.name not in app.blueprints:
        app.register_blueprint(stock_safety_bp)
    if multicolor_stock_bp.name not in app.blueprints:
        app.register_blueprint(multicolor_stock_bp)


def run_migrations():
    """Apply each versioned SQL migration once at application startup."""
    register_runtime_extensions()
    if not DATABASE_URL or not MIGRATIONS_DIR.exists():
        return
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            ''')
            conn.commit()
            for path in sorted(MIGRATIONS_DIR.glob('*.sql')):
                cur.execute('SELECT 1 FROM schema_migrations WHERE name=%s', (path.name,))
                if cur.fetchone():
                    continue
                cur.execute(path.read_text(encoding='utf-8'))
                cur.execute('INSERT INTO schema_migrations (name) VALUES (%s)', (path.name,))
                conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
