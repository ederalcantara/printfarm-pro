import html as html_lib
import os
import re

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import request

from app import app, ensure_schema
from migration_runner import run_migrations
from calculator import calculator_bp
from customer_portal import portal_bp
from online_requests import online_bp
from quote_flow import quote_flow_bp
from production import production_bp
from machine_admin import machine_admin_bp
from marketing import marketing_bp
from catalog_admin import catalog_admin_bp, ensure_catalog_schema
from data_cleanup import cleanup_bp
from payments import payments_bp, ensure_payment_schema
from business_tools import business_tools_bp
from customer_tools import customer_tools_bp
from public_site import public_site_bp
from operations import operations_bp

ensure_schema()
run_migrations()
app.register_blueprint(calculator_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(online_bp)
app.register_blueprint(quote_flow_bp)
app.register_blueprint(production_bp)
app.register_blueprint(machine_admin_bp)
app.register_blueprint(marketing_bp)
app.register_blueprint(catalog_admin_bp)
app.register_blueprint(cleanup_bp)
app.register_blueprint(payments_bp)
app.register_blueprint(business_tools_bp)
app.register_blueprint(customer_tools_bp)
app.register_blueprint(public_site_bp)
app.register_blueprint(operations_bp)
ensure_catalog_schema()
ensure_payment_schema()


def _production_snapshot():
    database_url = os.getenv('DATABASE_URL')
    result = {'active': [], 'queue': [], 'completed': []}
    if not database_url:return result
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT j.estimated_grams,j.started_at,q.quote_number,q.title,c.name AS customer_name,p.name AS project_name,m.name AS machine_name,m.model AS machine_model,f.material AS filament_material,f.color AS filament_color FROM print_jobs j JOIN quotes q ON q.id=j.quote_id LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN projects p ON p.id=j.project_id LEFT JOIN machines m ON m.id=j.machine_id LEFT JOIN filaments f ON f.id=j.filament_id WHERE j.status='printing' ORDER BY j.started_at DESC NULLS LAST""");result['active']=cur.fetchall()
                cur.execute("""SELECT q.id,q.quote_number,q.title,q.updated_at,c.name AS customer_name,p.name AS project_name FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN projects p ON p.quote_id=q.id WHERE q.status='execution' ORDER BY q.updated_at ASC""");result['queue']=cur.fetchall()
                cur.execute("""SELECT j.actual_grams,j.completed_at,q.quote_number,q.title,c.name AS customer_name,p.name AS project_name,m.name AS machine_name,f.material AS filament_material,f.color AS filament_color FROM print_jobs j JOIN quotes q ON q.id=j.quote_id LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN projects p ON p.id=j.project_id LEFT JOIN machines m ON m.id=j.machine_id LEFT JOIN filaments f ON f.id=j.filament_id WHERE j.status='completed' ORDER BY j.completed_at DESC NULLS LAST LIMIT 5""");result['completed']=cur.fetchall()
            except psycopg2.errors.UndefinedTable:conn.rollback();return result
    finally:conn.close()
    return result

def _payment_snapshot():
    result={'pending':[],'by_quote':{}};database_url=os.getenv('DATABASE_URL')
    if not database_url:return result
    conn=psycopg2.connect(database_url,cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT p.quote_id,p.status,p.method,p.amount_due,p.amount_paid,p.client_note,p.client_reported_at,q.quote_number,q.title,q.currency,c.name AS customer_name FROM quote_payments p JOIN quotes q ON q.id=p.quote_id LEFT JOIN customers c ON c.id=q.customer_id ORDER BY COALESCE(p.client_reported_at,p.updated_at) DESC""");rows=cur.fetchall();result['by_quote']={r['quote_number']:r for r in rows};result['pending']=[r for r in rows if r['status']=='pending_confirmation']
            except psycopg2.errors.UndefinedTable:conn.rollback()
    finally:conn.close()
    return result

def _esc(value,default='—'):return html_lib.escape(str(value if value not in (None,'') else default))
def _payment_badge(row):
    if not row:return '<span class="badge text-bg-secondary">Não liberado</span>'
    status=row.get('status');quote_id=row.get('quote_id')
    labels={'pending_confirmation':('danger','Cliente informou pagamento'),'paid':('success','Pago'),'deposit_paid':('success','Sinal pago'),'awaiting_payment':('warning','Aguardando pagamento')};kind,label=labels.get(status,('secondary','Não liberado'))
    return f'<span class="badge text-bg-{kind}">{label}</span><div class="mt-1"><a class="btn btn-sm btn-outline-dark" href="/quotes/{quote_id}/payment">Pagamento</a></div>'

@app.after_request
def inject_sidebar_links(response):
    if 'text/html' not in response.headers.get('Content-Type',''):return response
    page=response.get_data(as_text=True);marker='<a class="nav-link" href="/catalog" target="_blank">Catálogo público ↗</a>';additions=''
    for href,label in [('/orders','Pedidos'),('/online-requests','Pedidos Online'),('/sales-flow','Fluxo Comercial'),('/printing','Impressão'),('/production/stock','Produzir para Estoque'),('/business','Financeiro / Entregas'),('/marketing','Marketing / Instagram'),('/calculator','Calculadora'),('/admin/cleanup','Limpar dados de teste')]:
        if f'href="{href}"' not in page:additions+=f'<a class="nav-link" href="{href}">{label}</a>\n    '
    if marker in page and additions:page=page.replace(marker,additions+marker,1)
    machine_title='<div class="section-title">Máquinas</div>'
    if machine_title in page and 'href="/machines/manage"' not in page:page=page.replace(machine_title,'<div class="d-flex justify-content-between align-items-center mb-3"><div class="section-title mb-0">Máquinas</div><a class="btn btn-outline-dark" href="/machines/manage">Gerenciar / Excluir máquinas</a></div>',1)
    catalog_title='<div class="section-title">Catálogo Legacy</div>'
    if catalog_title in page and 'href="/catalog/manage"' not in page:page=page.replace(catalog_title,'<div class="d-flex justify-content-between align-items-center mb-3"><div class="section-title mb-0">Catálogo Legacy</div><a class="btn btn-outline-dark" href="/catalog/manage">Gerenciar peças e fotos</a></div>',1)
    payments=_payment_snapshot()
    if request.path=='/' and request.args.get('tab','dashboard')=='dashboard':
        s=_production_snapshot();active,queue,completed=s['active'],s['queue'],s['completed'];page=re.sub(r'(<div class="k">Imprimindo agora</div><div class="n">)\d+(</div>)',rf'\g<1>{len(active)}\2',page,count=1);blocks=[]
        if payments['pending']:
            rows=''.join(f'<tr><td><strong>{_esc(p.get("customer_name"))}</strong></td><td>{_esc(p.get("quote_number"))}</td><td>{_esc(p.get("method"),"").upper()}</td><td><strong>{_esc(p.get("amount_due"),0)}</strong></td><td><a class="btn btn-sm btn-danger" href="/quotes/{p.get("quote_id")}/payment">Confirmar pagamento</a></td></tr>' for p in payments['pending']);blocks.append(f'<div class="alert alert-warning border-warning mb-4"><strong>💰 Pagamentos aguardando sua confirmação: {len(payments["pending"])}</strong></div><div class="card mb-4"><div class="table-responsive"><table class="table mb-0"><tbody>{rows}</tbody></table></div></div>')
        blocks.append('<div class="row g-3 mb-4">'+f'<div class="col-md-4"><div class="card stat"><div class="k">Fila para imprimir</div><div class="n">{len(queue)}</div><a class="small" href="/printing">Abrir fila →</a></div></div>'+f'<div class="col-md-4"><div class="card stat"><div class="k">Imprimindo agora</div><div class="n">{len(active)}</div><a class="small" href="/printing">Ver impressão →</a></div></div>'+f'<div class="col-md-4"><div class="card stat"><div class="k">Concluídas recentes</div><div class="n">{len(completed)}</div><a class="small" href="/printing">Ver histórico →</a></div></div></div>')
        flow_marker='<div class="card p-4">\n        <h5>Fluxo de produção</h5>'
        if flow_marker in page:page=page.replace(flow_marker,''.join(blocks)+'\n      '+flow_marker,1)
    if request.path=='/' and request.args.get('tab')=='quotes':
        page=page.replace('<th>Produção</th><th>Status</th>','<th>Produção</th><th>Pagamento</th><th>Gestão</th><th>Status</th>',1)
        def add_cells(match):
            row=match.group(0);qm=re.search(r'<td class="mono">([^<]+)</td>',row)
            if not qm:return row
            number=html_lib.unescape(qm.group(1).strip());p=payments['by_quote'].get(number);pay='<td style="min-width:180px">'+_payment_badge(p)+'</td>';idmatch=re.search(r'/quotes/(\d+)/status',row);manage=f'<td><a class="btn btn-sm btn-outline-primary" href="/business/{idmatch.group(1)}">Financeiro / Entrega</a></td>' if idmatch else '<td>—</td>';marker_status='<td style="min-width:260px">'
            return row.replace(marker_status,pay+manage+marker_status,1) if marker_status in row else row
        page=re.sub(r'<tr><td class="mono">.*?</tr>',add_cells,page,flags=re.S)
    if request.path=='/' and request.args.get('tab')=='customers':
        def add_history(match):
            row=match.group(0)
            name_match=re.search(r'<td><strong>(.*?)</strong>',row,re.S)
            if not name_match:return row
            name=html_lib.unescape(re.sub('<.*?>','',name_match.group(1)).strip())
            conn=psycopg2.connect(os.getenv('DATABASE_URL'),cursor_factory=RealDictCursor)
            try:
                with conn.cursor() as cur:
                    cur.execute('SELECT id FROM customers WHERE name=%s ORDER BY id DESC LIMIT 1',(name,));rec=cur.fetchone()
            finally:conn.close()
            if not rec:return row
            return row.replace('</tr>',f'<td><a class="btn btn-sm btn-outline-primary" href="/customers/{rec["id"]}/history">Histórico</a></td></tr>',1)
        page=page.replace('<th>Observações</th></tr>','<th>Observações</th><th>Histórico</th></tr>',1)
        page=re.sub(r'<tr><td><strong>.*?</tr>',add_history,page,flags=re.S)
    response.set_data(page);response.headers['Content-Length']=str(len(response.get_data()));return response
