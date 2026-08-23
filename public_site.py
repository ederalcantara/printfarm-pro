import os

import psycopg2
from flask import Blueprint, render_template, session, redirect
from psycopg2.extras import RealDictCursor

public_site_bp = Blueprint('public_site', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def _products():
    if not DATABASE_URL:
        return []
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT p.id, p.name, p.description, p.price, p.currency,
                       EXISTS(SELECT 1 FROM product_images pi WHERE pi.product_id=p.id) AS has_image
                FROM products p
                WHERE p.active=TRUE
                ORDER BY p.created_at DESC
                LIMIT 8
            ''')
            return cur.fetchall()
    except Exception:
        return []
    finally:
        conn.close()


@public_site_bp.get('/home')
def public_home():
    return render_template('public_home.html', products=_products())


@public_site_bp.get('/admin')
def admin_entry():
    if session.get('user_id'):
        return redirect('/?admin=1')
    return redirect('/login')
