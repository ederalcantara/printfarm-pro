import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import wraps
from io import BytesIO

import psycopg2
from psycopg2.extras import RealDictCursor
from PIL import Image
from flask import Blueprint, Response, jsonify, render_template, request, session, redirect, url_for

marketing_bp = Blueprint('marketing', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')
APP_BASE_URL = (os.getenv('APP_BASE_URL') or 'https://sistema-legacy.onrender.com').rstrip('/')


def clean_token(value):
    value = (value or '').replace('\u200b', '').replace('\ufeff', '').strip().strip('"').strip("'").strip()
    return ''.join(value.split())


INSTAGRAM_ACCESS_TOKEN = clean_token(os.getenv('INSTAGRAM_ACCESS_TOKEN', ''))
INSTAGRAM_ACCOUNT_ID = (os.getenv('INSTAGRAM_ACCOUNT_ID', '') or '').strip()
INSTAGRAM_VERIFY_TOKEN = (os.getenv('INSTAGRAM_VERIFY_TOKEN', '') or '').strip()

ASSET_SCHEMA = '''
CREATE TABLE IF NOT EXISTS marketing_assets (
 id SERIAL PRIMARY KEY,
 public_token VARCHAR(80) UNIQUE NOT NULL,
 image_data BYTEA NOT NULL,
 content_type VARCHAR(80) NOT NULL DEFAULT 'image/jpeg',
 caption TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS scheduled_instagram_posts (
 id SERIAL PRIMARY KEY,
 public_token VARCHAR(80) NOT NULL,
 caption TEXT NOT NULL DEFAULT '',
 scheduled_at TIMESTAMPTZ NOT NULL,
 status VARCHAR(24) NOT NULL DEFAULT 'pending',
 attempts INTEGER NOT NULL DEFAULT 0,
 media_id TEXT,
 last_error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 published_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_scheduled_instagram_due
 ON scheduled_instagram_posts(status, scheduled_at);
'''


def db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def ensure_assets():
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute(ASSET_SCHEMA)
        c.commit()
    finally:
        c.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user_id'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def instagram_error(exc):
    detail = str(exc)
    if hasattr(exc, 'read'):
        try:
            detail = exc.read().decode('utf-8')
        except Exception:
            pass
    return detail


def token_meta():
    if not INSTAGRAM_ACCESS_TOKEN:
        return {'length': 0, 'prefix': '', 'fingerprint': ''}
    return {
        'length': len(INSTAGRAM_ACCESS_TOKEN),
        'prefix': INSTAGRAM_ACCESS_TOKEN[:5],
        'fingerprint': hashlib.sha256(INSTAGRAM_ACCESS_TOKEN.encode()).hexdigest()[:10],
    }


def instagram_get(path, params=None):
    params = dict(params or {})
    params['access_token'] = INSTAGRAM_ACCESS_TOKEN
    url = 'https://graph.instagram.com/' + path.lstrip('/') + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as exc:
        raise RuntimeError(instagram_error(exc))


def instagram_post(path, payload):
    url = 'https://graph.instagram.com/' + path.lstrip('/')
    body = urllib.parse.urlencode(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as exc:
        raise RuntimeError(instagram_error(exc))


def discover_instagram_user():
    info = instagram_get('me', {'fields': 'user_id,username'})
    uid = str(info.get('user_id') or info.get('id') or '')
    return uid, info.get('username') or ''


def wait_for_media_container(creation_id, attempts=20, delay=2):
    last = {}
    for _ in range(attempts):
        try:
            last = instagram_get(str(creation_id), {'fields': 'status_code,status'})
        except Exception as exc:
            print('INSTAGRAM_DIAG status_check_failed', str(exc)[:500], flush=True)
            time.sleep(delay)
            continue
        status = (last.get('status_code') or '').upper()
        print('INSTAGRAM_DIAG container_status', {'creation_id': creation_id, 'status': status}, flush=True)
        if status == 'FINISHED':
            return last
        if status in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'Falha no processamento da mídia pelo Instagram: {last}')
        time.sleep(delay)
    raise RuntimeError(f'Instagram não terminou de processar a mídia a tempo. Último status: {last}')


def png_to_instagram_jpeg(image_bytes):
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            img.load()
            if img.mode in ('RGBA', 'LA') or ('transparency' in img.info):
                rgba = img.convert('RGBA')
                background = Image.new('RGB', rgba.size, 'white')
                background.paste(rgba, mask=rgba.getchannel('A'))
                img = background
            else:
                img = img.convert('RGB')
            out = BytesIO()
            img.save(out, format='JPEG', quality=95, optimize=True, progressive=False)
            return out.getvalue()
    except Exception as exc:
        raise RuntimeError(f'Falha ao converter a arte para JPEG: {exc}')


def store_marketing_asset(image_bytes, caption=''):
    public_token = secrets.token_urlsafe(24)
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute(
                'INSERT INTO marketing_assets(public_token,image_data,content_type,caption) VALUES (%s,%s,%s,%s)',
                (public_token, psycopg2.Binary(image_bytes), 'image/jpeg', caption),
            )
        c.commit()
    finally:
        c.close()
    return public_token


def publish_asset(public_token, caption):
    if not INSTAGRAM_ACCESS_TOKEN:
        raise RuntimeError('INSTAGRAM_ACCESS_TOKEN não está configurado.')
    image_url = f'{APP_BASE_URL}/marketing/media/{public_token}.jpg'
    account_id, username = discover_instagram_user()
    if not account_id:
        raise RuntimeError('Instagram não retornou user_id da conta conectada.')
    created = instagram_post(
        f'{account_id}/media',
        {'image_url': image_url, 'caption': caption, 'access_token': INSTAGRAM_ACCESS_TOKEN},
    )
    creation_id = created.get('id')
    if not creation_id:
        raise RuntimeError('A Meta não retornou o ID do container de mídia.')
    wait_for_media_container(creation_id)
    published = instagram_post(
        f'{account_id}/media_publish',
        {'creation_id': creation_id, 'access_token': INSTAGRAM_ACCESS_TOKEN},
    )
    return {'media_id': published.get('id'), 'username': username}


def warm_web_service():
    try:
        req = urllib.request.Request(f'{APP_BASE_URL}/health', method='GET')
        with urllib.request.urlopen(req, timeout=90) as r:
            return 200 <= r.status < 300
    except Exception as exc:
        print('INSTAGRAM_SCHEDULER warm_failed', str(exc)[:300], flush=True)
        return False


def run_due_instagram_posts(limit=5):
    ensure_assets()
    warm_web_service()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute(
                '''SELECT * FROM scheduled_instagram_posts
                   WHERE status='pending' AND scheduled_at <= NOW()
                   ORDER BY scheduled_at ASC
                   LIMIT %s
                   FOR UPDATE SKIP LOCKED''',
                (limit,),
            )
            jobs = cur.fetchall()
            ids = [j['id'] for j in jobs]
            if ids:
                cur.execute(
                    '''UPDATE scheduled_instagram_posts
                       SET status='processing', attempts=attempts+1, updated_at=NOW()
                       WHERE id = ANY(%s)''',
                    (ids,),
                )
        c.commit()
    finally:
        c.close()

    processed = 0
    for job in jobs:
        processed += 1
        try:
            result = publish_asset(job['public_token'], job['caption'])
            c = db()
            try:
                with c.cursor() as cur:
                    cur.execute(
                        '''UPDATE scheduled_instagram_posts
                           SET status='published', media_id=%s, last_error=NULL,
                               published_at=NOW(), updated_at=NOW()
                           WHERE id=%s''',
                        (result.get('media_id'), job['id']),
                    )
                c.commit()
            finally:
                c.close()
            print('INSTAGRAM_SCHEDULER published', job['id'], result.get('media_id'), flush=True)
        except Exception as exc:
            error = str(exc)[:1500]
            c = db()
            try:
                with c.cursor() as cur:
                    cur.execute('SELECT attempts FROM scheduled_instagram_posts WHERE id=%s', (job['id'],))
                    row = cur.fetchone() or {'attempts': 3}
                    if row['attempts'] < 3:
                        cur.execute(
                            '''UPDATE scheduled_instagram_posts
                               SET status='pending', scheduled_at=NOW()+INTERVAL '5 minutes',
                                   last_error=%s, updated_at=NOW()
                               WHERE id=%s''',
                            (error, job['id']),
                        )
                    else:
                        cur.execute(
                            '''UPDATE scheduled_instagram_posts
                               SET status='failed', last_error=%s, updated_at=NOW()
                               WHERE id=%s''',
                            (error, job['id']),
                        )
                c.commit()
            finally:
                c.close()
            print('INSTAGRAM_SCHEDULER failed', job['id'], error, flush=True)
    return processed


@marketing_bp.get('/marketing')
@login_required
def marketing_home():
    ensure_assets()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute("SELECT id,sku,name,description,price,currency,stock_qty,(image_data IS NOT NULL) AS has_image FROM products WHERE active=TRUE ORDER BY created_at DESC")
            products = cur.fetchall()
    finally:
        c.close()
    return render_template('marketing.html', products=products, instagram_ready=bool(INSTAGRAM_ACCESS_TOKEN))


@marketing_bp.route('/marketing/scheduler', methods=['GET', 'POST'])
@login_required
def marketing_scheduler():
    ensure_assets()
    message = None
    error = None
    if request.method == 'POST':
        file = request.files.get('image')
        caption = (request.form.get('caption') or '').strip()
        scheduled_local = (request.form.get('scheduled_at') or '').strip()
        if not file or not scheduled_local:
            error = 'Escolha uma imagem e informe a data/hora.'
        else:
            try:
                raw = file.read()
                image_bytes = png_to_instagram_jpeg(raw)
                dt = datetime.fromisoformat(scheduled_local)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                scheduled_at = dt.astimezone(timezone.utc)
                public_token = store_marketing_asset(image_bytes, caption)
                c = db()
                try:
                    with c.cursor() as cur:
                        cur.execute(
                            '''INSERT INTO scheduled_instagram_posts(public_token,caption,scheduled_at)
                               VALUES (%s,%s,%s)''',
                            (public_token, caption, scheduled_at),
                        )
                    c.commit()
                finally:
                    c.close()
                message = 'Publicação adicionada à fila.'
            except Exception as exc:
                error = str(exc)
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute(
                '''SELECT id,caption,scheduled_at,status,attempts,media_id,last_error,published_at
                   FROM scheduled_instagram_posts
                   ORDER BY scheduled_at DESC LIMIT 50'''
            )
            posts = cur.fetchall()
    finally:
        c.close()
    return render_template('marketing_scheduler.html', posts=posts, message=message, error=error)


@marketing_bp.post('/marketing/scheduler/<int:post_id>/cancel')
@login_required
def cancel_scheduled_post(post_id):
    ensure_assets()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute(
                "UPDATE scheduled_instagram_posts SET status='canceled', updated_at=NOW() WHERE id=%s AND status='pending'",
                (post_id,),
            )
        c.commit()
    finally:
        c.close()
    return redirect(url_for('marketing.marketing_scheduler'))


@marketing_bp.get('/marketing/instagram-check')
@login_required
def instagram_check():
    if not INSTAGRAM_ACCESS_TOKEN:
        return jsonify(ok=False, error='INSTAGRAM_ACCESS_TOKEN não está configurado no Render.'), 400
    meta = token_meta()
    print('INSTAGRAM_DIAG check', meta, flush=True)
    try:
        uid, username = discover_instagram_user()
        return jsonify(ok=True, username=username, account_id=uid, message=f'Conexão válida com @{username}.')
    except Exception as exc:
        print('INSTAGRAM_DIAG auth_failed', meta, str(exc)[:500], flush=True)
        return jsonify(ok=False, error=f'Falha na autenticação do Instagram: {exc}', diagnostic=meta), 502


@marketing_bp.post('/marketing/publish-instagram')
@login_required
def publish_instagram():
    ensure_assets()
    if not INSTAGRAM_ACCESS_TOKEN:
        return jsonify(ok=False, error='Instagram ainda não está conectado no Render. Falta INSTAGRAM_ACCESS_TOKEN.'), 400
    meta = token_meta()
    print('INSTAGRAM_DIAG publish_start', meta, flush=True)
    payload = request.get_json(silent=True) or {}
    data_url = payload.get('image_data', '')
    caption = (payload.get('caption') or '').strip()
    fmt = payload.get('format', 'feed')
    if fmt != 'feed':
        return jsonify(ok=False, error='A publicação direta está liberada primeiro para Feed 1080×1080.'), 400
    if not data_url.startswith('data:image/png;base64,'):
        return jsonify(ok=False, error='Arte PNG inválida.'), 400
    try:
        source_bytes = base64.b64decode(data_url.split(',', 1)[1], validate=True)
        image_bytes = png_to_instagram_jpeg(source_bytes)
    except Exception as exc:
        return jsonify(ok=False, error=str(exc)), 400
    if len(image_bytes) > 8 * 1024 * 1024:
        return jsonify(ok=False, error='A arte JPEG ficou grande demais para publicação.'), 400
    public_token = store_marketing_asset(image_bytes, caption)
    try:
        result = publish_asset(public_token, caption)
        return jsonify(ok=True, media_id=result.get('media_id'), message=f"Publicado no Instagram @{result.get('username')} com sucesso.")
    except Exception as exc:
        print('INSTAGRAM_DIAG publish_failed', meta, str(exc)[:800], flush=True)
        return jsonify(ok=False, error=f'Instagram recusou a publicação: {exc}', diagnostic=meta), 502


@marketing_bp.get('/marketing/media/<token>.jpg')
def marketing_asset_jpg(token):
    ensure_assets()
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT image_data,content_type FROM marketing_assets WHERE public_token=%s', (token,))
            row = cur.fetchone()
    finally:
        c.close()
    if not row:
        return 'Imagem não encontrada', 404
    return Response(
        bytes(row['image_data']),
        mimetype='image/jpeg',
        headers={
            'Cache-Control': 'public, max-age=86400',
            'Content-Disposition': 'inline; filename="instagram.jpg"',
            'X-Content-Type-Options': 'nosniff',
        },
    )


@marketing_bp.route('/instagram/webhook', methods=['GET', 'POST'])
def instagram_webhook():
    if request.method == 'GET':
        mode = request.args.get('hub.mode')
        token = request.args.get('hub.verify_token')
        challenge = request.args.get('hub.challenge', '')
        if mode == 'subscribe' and INSTAGRAM_VERIFY_TOKEN and token == INSTAGRAM_VERIFY_TOKEN:
            return Response(challenge, mimetype='text/plain')
        return 'Verification failed', 403
    return jsonify(received=True)
