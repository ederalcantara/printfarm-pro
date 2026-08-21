import html as html_lib
import os
import re

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import request

from app import app
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
ensure_catalog_schema()
ensure_payment_schema()


def _production_snapshot():
    database_url = os.getenv('DATABASE_URL')
    result = {'active': [], 'queue': [], 'completed': []}
    if not database_url: return result
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            try:
                cur.execute("""SELECT j.estimated_grams,j.started_at,q.quote_number,q.title,c.name AS customer_name,p.name AS project_name,m.name AS machine_name,m.model AS machine_model,f.material AS filament_material,f.color AS filament_color FROM print_jobs j JOIN quotes q ON q.id=j.quote_id LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN projects p ON p.id=j.project_id LEFT JOIN machines m ON m.id=j.machine_id LEFT JOIN filaments f ON f.id=j.filament_id WHERE j.status='printing' ORDER BY j.started_at DESC NULLS LAST"""); result['active']=cur.fetchall()
                cur.execute("""SELECT q.id,q.quote_number,q.title,q.updated_at,c.name AS customer_name,p.name AS project_name FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN projects p ON p.quote_id=q.id WHERE q.status='execution' ORDER BY q.updated_at ASC"""); result['queue']=cur.fetchall()
                cur.execute("""SELECT j.actual_grams,j.completed_at,q.quote_number,q.title,c.name AS customer_name,p.name AS project_name,m.name AS machine_name,f.material AS filament_material,f.color AS filament_color FROM print_jobs j JOIN quotes q ON q.id=j.quote_id LEFT JOIN customers c ON c.id=q.customer_id LEFT JOIN projects p ON p.id=j.project_id LEFT JOIN machines m ON m.id=j.machine_id LEFT JOIN filaments f ON f.id=j.filament_id WHERE j.status='completed' ORDER BY j.completed_at DESC NULLS LAST LIMIT 5"""); result['completed']=cur.fetchall()
            except psycopg2.errors.UndefinedTable:
                conn.rollback(); return result
    finally: conn.close()
    return result

def _esc(value,default='—'): return html_lib.escape(str(value if value not in (None,'') else default))

@app.after_request
def inject_sidebar_links(response):
    content_type=response.headers.get('Content-Type','')
    if 'text/html' not in content_type:return response
    page=response.get_data(as_text=True)
    marker='<a class="nav-link" href="/catalog" target="_blank">Catálogo público ↗</a>'
    additions=''
    for href,label in [('/online-requests','Pedidos Online'),('/sales-flow','Fluxo Comercial'),('/printing','Impressão'),('/marketing','Marketing / Instagram'),('/calculator','Calculadora'),('/admin/cleanup','Limpar dados de teste')]:
        if f'href="{href}"' not in page:additions+=f'<a class="nav-link" href="{href}">{label}</a>\n    '
    if marker in page and additions:page=page.replace(marker,additions+marker,1)
    machine_title='<div class="section-title">Máquinas</div>'
    if machine_title in page and 'href="/machines/manage"' not in page:page=page.replace(machine_title,'<div class="d-flex justify-content-between align-items-center mb-3"><div class="section-title mb-0">Máquinas</div><a class="btn btn-outline-dark" href="/machines/manage">Gerenciar / Excluir máquinas</a></div>',1)
    catalog_title='<div class="section-title">Catálogo Legacy</div>'
    if catalog_title in page and 'href="/catalog/manage"' not in page:page=page.replace(catalog_title,'<div class="d-flex justify-content-between align-items-center mb-3"><div class="section-title mb-0">Catálogo Legacy</div><a class="btn btn-outline-dark" href="/catalog/manage">Gerenciar peças e fotos</a></div>',1)
    if request.path=='/' and request.args.get('tab','dashboard')=='dashboard':
        s=_production_snapshot(); active=s['active']; queue=s['queue']; completed=s['completed']
        page=re.sub(r'(<div class="k">Imprimindo agora</div><div class="n">)\d+(</div>)',rf'\g<1>{len(active)}\2',page,count=1)
        summary='<div class="row g-3 mb-4">'+f'<div class="col-md-4"><div class="card stat"><div class="k">Fila para imprimir</div><div class="n">{len(queue)}</div><a class="small" href="/printing">Abrir fila →</a></div></div>'+f'<div class="col-md-4"><div class="card stat"><div class="k">Imprimindo agora</div><div class="n">{len(active)}</div><a class="small" href="/printing">Ver impressão →</a></div></div>'+f'<div class="col-md-4"><div class="card stat"><div class="k">Concluídas recentes</div><div class="n">{len(completed)}</div><a class="small" href="/printing">Ver histórico →</a></div></div></div>'
        blocks=[summary]
        if queue:
            rows=''.join(f'<tr><td><strong>{_esc(i.get("project_name") or i.get("title"))}</strong><div class="small text-secondary">{_esc(i.get("quote_number"),"")}</div></td><td>{_esc(i.get("customer_name"))}</td><td><span class="badge text-bg-warning">Aguardando início</span></td></tr>' for i in queue); blocks.append('<div class="card mb-4"><div class="p-3 border-bottom"><strong>Fila para imprimir</strong></div><div class="table-responsive"><table class="table mb-0"><tbody>'+rows+'</tbody></table></div></div>')
        if active:
            rows=''.join(f'<tr><td><strong>{_esc(i.get("project_name") or i.get("title"))}</strong></td><td>{_esc(i.get("customer_name"))}</td><td>{_esc(i.get("machine_name"))}</td><td>{_esc(i.get("filament_material"))} · {_esc(i.get("filament_color"))}</td><td>{_esc(i.get("estimated_grams"),0)} g</td></tr>' for i in active); blocks.append('<div class="card mb-4"><div class="p-3 border-bottom"><strong>Imprimindo agora</strong></div><table class="table mb-0"><tbody>'+rows+'</tbody></table></div>')
        else:blocks.append('<div class="card p-3 mb-4"><strong>Nenhuma impressão ativa</strong><div class="text-secondary small">Um trabalho aparece aqui depois de clicar em Iniciar impressão.</div></div>')
        if completed:
            rows=''.join(f'<tr><td><strong>{_esc(i.get("project_name") or i.get("title"))}</strong></td><td>{_esc(i.get("customer_name"))}</td><td>{_esc(i.get("machine_name"))}</td><td>{_esc(i.get("actual_grams"),0)} g</td></tr>' for i in completed); blocks.append('<div class="card mb-4"><div class="p-3 border-bottom"><strong>Últimas impressões concluídas</strong></div><table class="table mb-0"><tbody>'+rows+'</tbody></table></div>')
        flow_marker='<div class="card p-4">\n        <h5>Fluxo de produção</h5>'
        if flow_marker in page:page=page.replace(flow_marker,''.join(blocks)+'\n      '+flow_marker,1)
    response.set_data(page); response.headers['Content-Length']=str(len(response.get_data())); return response
