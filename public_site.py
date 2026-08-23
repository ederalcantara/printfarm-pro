import os

import psycopg2
from flask import Blueprint, render_template, session, redirect, request, current_app
from psycopg2.extras import RealDictCursor

public_site_bp = Blueprint('public_site', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def _ensure_public_columns(conn):
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_data BYTEA")
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_content_type VARCHAR(120)")
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_name VARCHAR(255)")
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS collection VARCHAR(30) NOT NULL DEFAULT 'catalog'")
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 1000")
        cur.execute("UPDATE products SET collection='exclusive' WHERE lower(COALESCE(sku,'')) ~ '^legacy[ _-]*0*(1[0-4]|[1-9])$' AND collection='catalog'")
    conn.commit()


def _products():
    result={'exclusive':[],'catalog':[]}
    if not DATABASE_URL:
        current_app.logger.error('Public catalog: DATABASE_URL is not configured'); return result
    conn=None
    try:
        conn=psycopg2.connect(DATABASE_URL,cursor_factory=RealDictCursor)
        _ensure_public_columns(conn)
        with conn.cursor() as cur:
            cur.execute('''SELECT id,sku,name,description,price,currency,collection,display_order,
                                  image_data IS NOT NULL AS has_image
                           FROM products
                           WHERE active IS TRUE
                           ORDER BY display_order ASC, created_at DESC, id DESC''')
            for p in cur.fetchall():
                result['exclusive' if p.get('collection')=='exclusive' else 'catalog'].append(p)
        return result
    except Exception:
        current_app.logger.exception('Public catalog failed to load products'); return result
    finally:
        if conn is not None: conn.close()


def _whatsapp_url():
    number=''.join(ch for ch in os.getenv('WHATSAPP_NUMBER','17743757803') if ch.isdigit())
    return f'https://wa.me/{number}?text=Olá%20Legacy%203D%20Studio!%20Gostaria%20de%20mais%20informações.'


@public_site_bp.before_app_request
def public_main_domain():
    if request.path=='/' and not session.get('user_id'): return redirect('/home')


@public_site_bp.get('/home')
def public_home():
    groups=_products()
    return render_template('public_home.html',exclusive_products=groups['exclusive'],catalog_products=groups['catalog'],whatsapp_url=_whatsapp_url())


@public_site_bp.get('/admin')
def admin_entry():
    if session.get('user_id'): return redirect('/')
    return redirect('/login')
