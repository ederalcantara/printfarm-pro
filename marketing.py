import base64
import hashlib
import json
import os
import secrets
import urllib.parse
import urllib.request
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Blueprint, Response, jsonify, render_template, request, session, redirect, url_for

marketing_bp = Blueprint('marketing', __name__)
DATABASE_URL = os.getenv('DATABASE_URL')


def _clean_token(value):
    """Normalize secrets copied through dashboards without ever logging the secret."""
    value = (value or '').strip().strip('"').strip("'").strip()
    # Access tokens never legitimately contain whitespace. Remove accidental CR/LF/spaces
    # introduced by copy/paste or multiline environment editors.
    return ''.join(value.split())


INSTAGRAM_ACCESS_TOKEN = _clean_token(os.getenv('INSTAGRAM_ACCESS_TOKEN', ''))
INSTAGRAM_ACCOUNT_ID = (os.getenv('INSTAGRAM_ACCOUNT_ID', '17841433632592241') or '').strip()
INSTAGRAM_GRAPH_VERSION = (os.getenv('INSTAGRAM_GRAPH_VERSION', 'v26.0') or 'v26.0').strip()
INSTAGRAM_VERIFY_TOKEN = (os.getenv('INSTAGRAM_VERIFY_TOKEN', '') or '').strip()

ASSET_SCHEMA = '''
CREATE TABLE IF NOT EXISTS marketing_assets (
 id SERIAL PRIMARY KEY,
 public_token VARCHAR(80) UNIQUE NOT NULL,
 image_data BYTEA NOT NULL,
 content_type VARCHAR(80) NOT NULL DEFAULT 'image/png',
 caption TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
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


def token_diagnostics():
    if not INSTAGRAM_ACCESS_TOKEN:
        return {'configured': False, 'length': 0, 'prefix': '', 'fingerprint': ''}
    return {
        'configured': True,
        'length': len(INSTAGRAM_ACCESS_TOKEN),
        'prefix': INSTAGRAM_ACCESS_TOKEN[:5],
        'fingerprint': hashlib.sha256(INSTAGRAM_ACCESS_TOKEN.encode('utf-8')).hexdigest()[:10],
    }


def instagram_error(exc):
    detail = str(exc)
    if hasattr(exc, 'read'):
        try:
            detail = exc.read().decode('utf-8')
        except Exception:
            pass
    return detail


def instagram_get(path, params=None):
    params = dict(params or {})
    params['access_token'] = INSTAGRAM_ACCESS_TOKEN
    url = f'https://graph.instagram.com/{INSTAGRAM_GRAPH_VERSION}/{path.lstrip("/")}?{urllib.parse.urlencode(params)}'
    req = urllib.request.Request(url, method='GET', headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as exc:
        raise RuntimeError(instagram_error(exc))


def instagram_post(path, payload):
    url = f'https://graph.instagram.com/{INSTAGRAM_GRAPH_VERSION}/{path.lstrip("/")}'
    body = urllib.parse.urlencode(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={
        'Accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as exc:
        raise RuntimeError(instagram_error(exc))


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
    return render_template('marketing.html', products=products, instagram_ready=bool(INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID))


@marketing_bp.get('/marketing/instagram-check')
@login_required
def instagram_check():
    diag = token_diagnostics()
    if not INSTAGRAM_ACCESS_TOKEN:
        return jsonify(ok=False, diagnostics=diag, error='INSTAGRAM_ACCESS_TOKEN não está configurado no Render.'), 400
    try:
        info = instagram_get('me', {'fields': 'id,username'})
        returned_id = str(info.get('id') or '')
        username = info.get('username') or 'conta conectada'
        if INSTAGRAM_ACCOUNT_ID and returned_id and returned_id != INSTAGRAM_ACCOUNT_ID:
            return jsonify(ok=False, diagnostics=diag, error=f'O token é válido, mas pertence à conta {username} ({returned_id}), enquanto o Render está configurado para {INSTAGRAM_ACCOUNT_ID}.'), 409
        return jsonify(ok=True, diagnostics=diag, username=username, account_id=returned_id, message=f'Conexão válida com @{username}.')
    except Exception as exc:
        print(f'[instagram-auth] validation failed diag={diag} error={exc}', flush=True)
        return jsonify(ok=False, diagnostics=diag, error=f'Falha na validação do token: {exc}'), 502


@marketing_bp.post('/marketing/publish-instagram')
@login_required
def publish_instagram():
    ensure_assets()
    diag = token_diagnostics()
    if not INSTAGRAM_ACCESS_TOKEN:
        return jsonify(ok=False, diagnostics=diag, error='Instagram ainda não está conectado no Render. Falta INSTAGRAM_ACCESS_TOKEN.'), 400

    payload = request.get_json(silent=True) or {}
    data_url = payload.get('image_data', '')
    caption = (payload.get('caption') or '').strip()
    fmt = payload.get('format', 'feed')
    if fmt != 'feed':
        return jsonify(ok=False, error='A publicação direta está liberada primeiro para Feed 1080×1080. Use Feed para este teste.'), 400
    if not data_url.startswith('data:image/png;base64,'):
        return jsonify(ok=False, error='Arte PNG inválida.'), 400
    try:
        image_bytes = base64.b64decode(data_url.split(',', 1)[1], validate=True)
    except Exception:
        return jsonify(ok=False, error='Não foi possível ler a arte.'), 400
    if len(image_bytes) > 12 * 1024 * 1024:
        return jsonify(ok=False, error='A arte ficou grande demais para publicação.'), 400

    # Validate authentication before storing/rendering an asset. This prevents false
    # publishing errors and provides a safe fingerprint for Render diagnostics.
    try:
        info = instagram_get('me', {'fields': 'id,username'})
        returned_id = str(info.get('id') or '')
        if returned_id and INSTAGRAM_ACCOUNT_ID and returned_id != INSTAGRAM_ACCOUNT_ID:
            return jsonify(ok=False, diagnostics=diag, error=f'Token válido, porém o ID da conta é {returned_id}; ajuste INSTAGRAM_ACCOUNT_ID no Render.'), 409
    except Exception as exc:
        print(f'[instagram-auth] publish blocked diag={diag} account_id={INSTAGRAM_ACCOUNT_ID} error={exc}', flush=True)
        return jsonify(ok=False, diagnostics=diag, error=f'Autenticação do Instagram falhou antes da publicação: {exc}'), 502

    public_token = secrets.token_urlsafe(24)
    c = db()
    try:
        with c.cursor() as cur:
            cur.execute('INSERT INTO marketing_assets(public_token,image_data,caption) VALUES (%s,%s,%s)',
                        (public_token, psycopg2.Binary(image_bytes), caption))
        c.commit()
    finally:
        c.close()

    image_url = request.url_root.rstrip('/') + url_for('marketing.marketing_asset', token=public_token)
    try:
        created = instagram_post(f'{INSTAGRAM_ACCOUNT_ID}/media', {
            'image_url': image_url,
            'caption': caption,
            'access_token': INSTAGRAM_ACCESS_TOKEN,
        })
        creation_id = created.get('id')
        if not creation_id:
            raise RuntimeError('A Meta não retornou o ID do container de mídia.')
        published = instagram_post(f'{INSTAGRAM_ACCOUNT_ID}/media_publish', {
            'creation_id': creation_id,
            'access_token': INSTAGRAM_ACCESS_TOKEN,
        })
        return jsonify(ok=True, media_id=published.get('id'), message='Publicado no Instagram com sucesso.')
    except Exception as exc:
        print(f'[instagram-publish] diag={diag} account_id={INSTAGRAM_ACCOUNT_ID} image_url={image_url} error={exc}', flush=True)
        return jsonify(ok=False, diagnostics=diag, error=f'Instagram recusou a publicação: {exc}'), 502


@marketing_bp.get('/marketing/media/<token>.png')
def marketing_asset(token):
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
    return Response(bytes(row['image_data']), mimetype=row['content_type'], headers={'Cache-Control': 'public, max-age=86400'})


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
