import os

import psycopg2
from flask import Blueprint, render_template, session, redirect, request
from psycopg2.extras import RealDictCursor

public_site_bp = Blueprint('public_site', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def _products():
    result = {'exclusive': [], 'catalog': []}
    if not DATABASE_URL:
        return result
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT p.id, p.sku, p.name, p.description, p.price, p.currency,
                       p.image_data IS NOT NULL AS has_image
                FROM products p
                WHERE p.active=TRUE
                ORDER BY p.created_at DESC
            ''')
            for p in cur.fetchall():
                sku = (p.get('sku') or '').strip().lower()
                is_exclusive = False
                if sku.startswith('legacy '):
                    try:
                        number = int(sku.split()[-1])
                        is_exclusive = 1 <= number <= 14
                    except (ValueError, IndexError):
                        pass
                result['exclusive' if is_exclusive else 'catalog'].append(p)
            return result
    except Exception:
        return result
    finally:
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
    return render_template('public_home.html', exclusive_products=groups['exclusive'], catalog_products=groups['catalog'], whatsapp_url=_whatsapp_url())


@public_site_bp.get('/admin')
def admin_entry():
    if session.get('user_id'):
        return redirect('/')
    return redirect('/login')
