import os
import re

import psycopg2
from flask import Blueprint, render_template, session, redirect, request, current_app
from psycopg2.extras import RealDictCursor

public_site_bp = Blueprint('public_site', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def _ensure_image_columns(conn):
    """Keep the public catalog compatible with products created before image support was added."""
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_data BYTEA")
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_content_type VARCHAR(120)")
        cur.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_name VARCHAR(255)")
    conn.commit()


def _legacy_number(sku):
    """Accept Legacy 001, LEGACY-001, Legacy001 and similar SKU formatting."""
    text = (sku or '').strip()
    match = re.search(r'(?i)\blegacy\s*[-_ ]*0*(\d+)\b', text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _products():
    result = {'exclusive': [], 'catalog': []}
    if not DATABASE_URL:
        current_app.logger.error('Public catalog: DATABASE_URL is not configured')
        return result

    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        _ensure_image_columns(conn)
        with conn.cursor() as cur:
            cur.execute('''
                SELECT id, sku, name, description, price, currency,
                       image_data IS NOT NULL AS has_image
                FROM products
                WHERE active IS TRUE
                ORDER BY created_at DESC, id DESC
            ''')
            products = cur.fetchall()

        for p in products:
            legacy_no = _legacy_number(p.get('sku'))
            if legacy_no is not None and 1 <= legacy_no <= 14:
                p['legacy_number'] = legacy_no
                result['exclusive'].append(p)
            else:
                result['catalog'].append(p)

        result['exclusive'].sort(key=lambda p: p.get('legacy_number', 9999))
        return result
    except Exception:
        current_app.logger.exception('Public catalog failed to load products')
        return result
    finally:
        if conn is not None:
            conn.close()


def _whatsapp_url():
    number = ''.join(ch for ch in os.getenv('WHATSAPP_NUMBER', '17743757803') if ch.isdigit())
    return f'https://wa.me/{number}?text=Olá%20Legacy%203D%20Studio!%20Gostaria%20de%20mais%20informações.'


@public_site_bp.before_app_request
def public_main_domain():
    if request.path == '/' and not session.get('user_id'):
        return redirect('/home')


@public_site_bp.get('/home')
def public_home():
    groups = _products()
    return render_template(
        'public_home.html',
        exclusive_products=groups['exclusive'],
        catalog_products=groups['catalog'],
        whatsapp_url=_whatsapp_url(),
    )


@public_site_bp.get('/admin')
def admin_entry():
    if session.get('user_id'):
        return redirect('/')
    return redirect('/login')
