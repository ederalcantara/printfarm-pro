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

app.register_blueprint(calculator_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(online_bp)
app.register_blueprint(quote_flow_bp)
app.register_blueprint(production_bp)
app.register_blueprint(machine_admin_bp)
app.register_blueprint(marketing_bp)


def _production_snapshot():
    database_url = os.getenv('DATABASE_URL')
    result = {'active': [], 'queue': [], 'completed': []}
    if not database_url:
        return result
    conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            try:
                cur.execute('''
                    SELECT j.estimated_grams, j.started_at,
                           q.quote_number, q.title,
                           c.name AS customer_name,
                           p.name AS project_name,
                           m.name AS machine_name, m.model AS machine_model,
                           f.material AS filament_material, f.color AS filament_color
                    FROM print_jobs j
                    JOIN quotes q ON q.id=j.quote_id
                    LEFT JOIN customers c ON c.id=q.customer_id
                    LEFT JOIN projects p ON p.id=j.project_id
                    LEFT JOIN machines m ON m.id=j.machine_id
                    LEFT JOIN filaments f ON f.id=j.filament_id
                    WHERE j.status='printing'
                    ORDER BY j.started_at DESC NULLS LAST
                ''')
                result['active'] = cur.fetchall()

                cur.execute('''
                    SELECT q.id, q.quote_number, q.title, q.updated_at,
                           c.name AS customer_name,
                           p.name AS project_name
                    FROM quotes q
                    LEFT JOIN customers c ON c.id=q.customer_id
                    LEFT JOIN projects p ON p.quote_id=q.id
                    WHERE q.status='execution'
                    ORDER BY q.updated_at ASC
                ''')
                result['queue'] = cur.fetchall()

                cur.execute('''
                    SELECT j.actual_grams, j.completed_at,
                           q.quote_number, q.title,
                           c.name AS customer_name,
                           p.name AS project_name,
                           m.name AS machine_name,
                           f.material AS filament_material, f.color AS filament_color
                    FROM print_jobs j
                    JOIN quotes q ON q.id=j.quote_id
                    LEFT JOIN customers c ON c.id=q.customer_id
                    LEFT JOIN projects p ON p.id=j.project_id
                    LEFT JOIN machines m ON m.id=j.machine_id
                    LEFT JOIN filaments f ON f.id=j.filament_id
                    WHERE j.status='completed'
                    ORDER BY j.completed_at DESC NULLS LAST
                    LIMIT 5
                ''')
                result['completed'] = cur.fetchall()
            except psycopg2.errors.UndefinedTable:
                conn.rollback()
                return result
    finally:
        conn.close()
    return result


def _esc(value, default='—'):
    return html_lib.escape(str(value if value not in (None, '') else default))


@app.after_request
def inject_sidebar_links(response):
    content_type = response.headers.get('Content-Type', '')
    if 'text/html' not in content_type:
        return response

    page = response.get_data(as_text=True)
    marker = '<a class="nav-link" href="/catalog" target="_blank">Catálogo público ↗</a>'
    additions = ''
    if 'href="/online-requests"' not in page:
        additions += '<a class="nav-link" href="/online-requests">Pedidos Online</a>\n    '
    if 'href="/sales-flow"' not in page:
        additions += '<a class="nav-link" href="/sales-flow">Fluxo Comercial</a>\n    '
    if 'href="/printing"' not in page:
        additions += '<a class="nav-link" href="/printing">Impressão</a>\n    '
    if 'href="/marketing"' not in page:
        additions += '<a class="nav-link" href="/marketing">Marketing / Instagram</a>\n    '
    if 'href="/calculator"' not in page:
        additions += '<a class="nav-link" href="/calculator">Calculadora</a>\n    '
    if marker in page and additions:
        page = page.replace(marker, additions + marker, 1)

    machine_title = '<div class="section-title">Máquinas</div>'
    if machine_title in page and 'href="/machines/manage"' not in page:
        page = page.replace(
            machine_title,
            '<div class="d-flex justify-content-between align-items-center mb-3"><div class="section-title mb-0">Máquinas</div><a class="btn btn-outline-dark" href="/machines/manage">Gerenciar / Excluir máquinas</a></div>',
            1,
        )

    if request.path == '/' and request.args.get('tab', 'dashboard') == 'dashboard':
        snapshot = _production_snapshot()
        active = snapshot['active']
        queue = snapshot['queue']
        completed = snapshot['completed']

        page = re.sub(
            r'(<div class="k">Imprimindo agora</div><div class="n">)\d+(</div>)',
            rf'\g<1>{len(active)}\2',
            page,
            count=1,
        )

        summary = (
            '<div class="row g-3 mb-4">'
            f'<div class="col-md-4"><div class="card stat"><div class="k">Fila para imprimir</div><div class="n">{len(queue)}</div><a class="small" href="/printing">Abrir fila →</a></div></div>'
            f'<div class="col-md-4"><div class="card stat"><div class="k">Imprimindo agora</div><div class="n">{len(active)}</div><a class="small" href="/printing">Ver impressão →</a></div></div>'
            f'<div class="col-md-4"><div class="card stat"><div class="k">Concluídas recentes</div><div class="n">{len(completed)}</div><a class="small" href="/printing">Ver histórico →</a></div></div>'
            '</div>'
        )

        blocks = [summary]

        if queue:
            rows = ''.join(
                f'<tr><td><strong>{_esc(i.get("project_name") or i.get("title"))}</strong><div class="small text-secondary">{_esc(i.get("quote_number"), "")}</div></td><td>{_esc(i.get("customer_name"))}</td><td><span class="badge text-bg-warning">Aguardando início</span></td></tr>'
                for i in queue
            )
            blocks.append('<div class="card mb-4"><div class="p-3 border-bottom d-flex justify-content-between"><strong>Fila para imprimir</strong><a href="/printing">Escolher máquina e filamento →</a></div><div class="table-responsive"><table class="table mb-0"><thead><tr><th>Projeto</th><th>Cliente</th><th>Status</th></tr></thead><tbody>' + rows + '</tbody></table></div></div>')

        if active:
            rows = []
            for item in active:
                rows.append(f'<tr><td><strong>{_esc(item.get("project_name") or item.get("title"))}</strong><div class="small text-secondary">{_esc(item.get("quote_number"), "")}</div></td><td>{_esc(item.get("customer_name"))}</td><td><strong>{_esc(item.get("machine_name"))}</strong><div class="small text-secondary">{_esc(item.get("machine_model"), "")}</div></td><td>{_esc(item.get("filament_material"))} · {_esc(item.get("filament_color"))}</td><td>{_esc(item.get("estimated_grams"), 0)} g</td></tr>')
            blocks.append('<div class="card mb-4"><div class="p-3 border-bottom d-flex justify-content-between"><strong>Imprimindo agora</strong><a href="/printing">Abrir painel →</a></div><div class="table-responsive"><table class="table mb-0"><thead><tr><th>Projeto</th><th>Cliente</th><th>Máquina</th><th>Filamento</th><th>Estimado</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div></div>')
        else:
            blocks.append('<div class="card p-3 mb-4"><div class="d-flex justify-content-between align-items-center"><div><strong>Nenhuma impressão ativa</strong><div class="text-secondary small">Um trabalho só aparece aqui depois de clicar em “Iniciar impressão” no painel Impressão.</div></div><a class="btn btn-sm btn-outline-dark" href="/printing">Abrir Impressão</a></div></div>')

        if completed:
            rows = ''.join(
                f'<tr><td><strong>{_esc(i.get("project_name") or i.get("title"))}</strong><div class="small text-secondary">{_esc(i.get("quote_number"), "")}</div></td><td>{_esc(i.get("customer_name"))}</td><td>{_esc(i.get("machine_name"))}</td><td>{_esc(i.get("filament_material"))} · {_esc(i.get("filament_color"))}</td><td>{_esc(i.get("actual_grams"), 0)} g</td></tr>'
                for i in completed
            )
            blocks.append('<div class="card mb-4"><div class="p-3 border-bottom"><strong>Últimas impressões concluídas</strong></div><div class="table-responsive"><table class="table mb-0"><thead><tr><th>Projeto</th><th>Cliente</th><th>Máquina</th><th>Filamento</th><th>Consumo real</th></tr></thead><tbody>' + rows + '</tbody></table></div></div>')

        flow_marker = '<div class="card p-4">\n        <h5>Fluxo de produção</h5>'
        if flow_marker in page:
            page = page.replace(flow_marker, ''.join(blocks) + '\n      ' + flow_marker, 1)

    response.set_data(page)
    response.headers['Content-Length'] = str(len(response.get_data()))
    return response
