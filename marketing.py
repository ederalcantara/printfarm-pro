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

def clean_token(value):
    value = (value or '').replace('\u200b','').replace('\ufeff','').strip().strip('"').strip("'").strip()
    return ''.join(value.split())

INSTAGRAM_ACCESS_TOKEN = clean_token(os.getenv('INSTAGRAM_ACCESS_TOKEN', ''))
INSTAGRAM_ACCOUNT_ID = (os.getenv('INSTAGRAM_ACCOUNT_ID', '') or '').strip()
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

def db(): return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def ensure_assets():
    c=db()
    try:
        with c.cursor() as cur: cur.execute(ASSET_SCHEMA)
        c.commit()
    finally:c.close()

def login_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not session.get('user_id'): return redirect(url_for('login'))
        return view(*args,**kwargs)
    return wrapped

def instagram_error(exc):
    detail=str(exc)
    if hasattr(exc,'read'):
        try: detail=exc.read().decode('utf-8')
        except Exception: pass
    return detail

def token_meta():
    if not INSTAGRAM_ACCESS_TOKEN:return {'length':0,'prefix':'','fingerprint':''}
    return {'length':len(INSTAGRAM_ACCESS_TOKEN),'prefix':INSTAGRAM_ACCESS_TOKEN[:5],'fingerprint':hashlib.sha256(INSTAGRAM_ACCESS_TOKEN.encode()).hexdigest()[:10]}

def instagram_get(path,params=None):
    params=dict(params or {});params['access_token']=INSTAGRAM_ACCESS_TOKEN
    url='https://graph.instagram.com/'+path.lstrip('/')+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,method='GET')
    try:
        with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read().decode('utf-8'))
    except Exception as exc:raise RuntimeError(instagram_error(exc))

def instagram_post(path,payload):
    url='https://graph.instagram.com/'+path.lstrip('/')
    body=urllib.parse.urlencode(payload).encode('utf-8')
    req=urllib.request.Request(url,data=body,method='POST')
    try:
        with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read().decode('utf-8'))
    except Exception as exc:raise RuntimeError(instagram_error(exc))

def discover_instagram_user():
    info=instagram_get('me',{'fields':'user_id,username'})
    uid=str(info.get('user_id') or info.get('id') or '')
    return uid,info.get('username') or ''

@marketing_bp.get('/marketing')
@login_required
def marketing_home():
    ensure_assets();c=db()
    try:
        with c.cursor() as cur:
            cur.execute("SELECT id,sku,name,description,price,currency,stock_qty,(image_data IS NOT NULL) AS has_image FROM products WHERE active=TRUE ORDER BY created_at DESC")
            products=cur.fetchall()
    finally:c.close()
    return render_template('marketing.html',products=products,instagram_ready=bool(INSTAGRAM_ACCESS_TOKEN))

@marketing_bp.get('/marketing/instagram-check')
@login_required
def instagram_check():
    if not INSTAGRAM_ACCESS_TOKEN:return jsonify(ok=False,error='INSTAGRAM_ACCESS_TOKEN não está configurado no Render.'),400
    meta=token_meta();print('INSTAGRAM_DIAG check',meta,flush=True)
    try:
        uid,username=discover_instagram_user()
        return jsonify(ok=True,username=username,account_id=uid,message=f'Conexão válida com @{username}.')
    except Exception as exc:
        print('INSTAGRAM_DIAG auth_failed',meta,str(exc)[:500],flush=True)
        return jsonify(ok=False,error=f'Falha na autenticação do Instagram: {exc}',diagnostic=meta),502

@marketing_bp.post('/marketing/publish-instagram')
@login_required
def publish_instagram():
    ensure_assets()
    if not INSTAGRAM_ACCESS_TOKEN:return jsonify(ok=False,error='Instagram ainda não está conectado no Render. Falta INSTAGRAM_ACCESS_TOKEN.'),400
    meta=token_meta();print('INSTAGRAM_DIAG publish_start',meta,flush=True)
    payload=request.get_json(silent=True) or {};data_url=payload.get('image_data','');caption=(payload.get('caption') or '').strip();fmt=payload.get('format','feed')
    if fmt!='feed':return jsonify(ok=False,error='A publicação direta está liberada primeiro para Feed 1080×1080.'),400
    if not data_url.startswith('data:image/png;base64,'):return jsonify(ok=False,error='Arte PNG inválida.'),400
    try:image_bytes=base64.b64decode(data_url.split(',',1)[1],validate=True)
    except Exception:return jsonify(ok=False,error='Não foi possível ler a arte.'),400
    public_token=secrets.token_urlsafe(24);c=db()
    try:
        with c.cursor() as cur:cur.execute('INSERT INTO marketing_assets(public_token,image_data,caption) VALUES (%s,%s,%s)',(public_token,psycopg2.Binary(image_bytes),caption))
        c.commit()
    finally:c.close()
    image_url=request.url_root.rstrip('/')+url_for('marketing.marketing_asset',token=public_token)
    try:
        account_id,username=discover_instagram_user()
        print('INSTAGRAM_DIAG auth_ok',{'username':username,'account_id':account_id},flush=True)
        if not account_id:raise RuntimeError('Instagram não retornou user_id da conta conectada.')
        created=instagram_post(f'{account_id}/media',{'image_url':image_url,'caption':caption,'access_token':INSTAGRAM_ACCESS_TOKEN})
        creation_id=created.get('id')
        if not creation_id:raise RuntimeError('A Meta não retornou o ID do container de mídia.')
        published=instagram_post(f'{account_id}/media_publish',{'creation_id':creation_id,'access_token':INSTAGRAM_ACCESS_TOKEN})
        return jsonify(ok=True,media_id=published.get('id'),message=f'Publicado no Instagram @{username} com sucesso.')
    except Exception as exc:
        print('INSTAGRAM_DIAG publish_failed',meta,str(exc)[:800],flush=True)
        return jsonify(ok=False,error=f'Instagram recusou a publicação: {exc}',diagnostic=meta),502

@marketing_bp.get('/marketing/media/<token>.png')
def marketing_asset(token):
    ensure_assets();c=db()
    try:
        with c.cursor() as cur:cur.execute('SELECT image_data,content_type FROM marketing_assets WHERE public_token=%s',(token,));row=cur.fetchone()
    finally:c.close()
    if not row:return 'Imagem não encontrada',404
    return Response(bytes(row['image_data']),mimetype=row['content_type'],headers={'Cache-Control':'public, max-age=86400'})

@marketing_bp.route('/instagram/webhook',methods=['GET','POST'])
def instagram_webhook():
    if request.method=='GET':
        mode=request.args.get('hub.mode');token=request.args.get('hub.verify_token');challenge=request.args.get('hub.challenge','')
        if mode=='subscribe' and INSTAGRAM_VERIFY_TOKEN and token==INSTAGRAM_VERIFY_TOKEN:return Response(challenge,mimetype='text/plain')
        return 'Verification failed',403
    return jsonify(received=True)
