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

app.register_blueprint(calculator_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(online_bp)
app.register_blueprint(quote_flow_bp)
app.register_blueprint(production_bp)
app.register_blueprint(machine_admin_bp)


def _active_prints():
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        return []
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
                return cur.fetchall()
            except psycopg2.errors.UndefinedTable:
                conn.rollback()
                return []
    finally:
        conn.close()


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
    if 'href="/calculator"' not in page:
        additions += '<a class="nav-link" href="/calculator">Calculadora</a>\n    '
    if marker in page and additions:
        page = page.replace(marker, additions + marker, 1)

    # Add machine management to the existing Machines page.
    machine_title = '<div class="section-title">Máquinas</div>'
    if machine_title in page and 'href="/machines/manage"' not in page:
        page = page.replace(
            machine_title,
            '<div class="d-flex justify-content-between align-items-center mb-3"><div class="section-title mb-0">Máquinas</div><a class="btn btn-outline-dark" href="/machines/manage">Gerenciar / Excluir máquinas</a></div>',
            1,
        )

    # Make Dashboard "Imprimindo agora" operational, not only a counter.
    if request.path == '/' and request.args.get('tab', 'dashboard') == 'dashboard':
        active = _active_prints()
        count = len(active)
        page = re.sub(
            r'(<div class="k">Imprimindo agora</div><div class="n">)\d+(</div>)',
            rf'\g<1>{count}\2',
            page,
            count=1,
        )
        rows = []
        for item in active:
            customer = html_lib.escape(str(item.get('customer_name') or '—'))
            project = html_lib.escape(str(item.get('project_name') or item.get('title') or '—'))
            machine = html_lib.escape(str(item.get('machine_name') or '—'))
            model = html_lib.escape(str(item.get('machine_model') or ''))
            filament = html_lib.escape(f"{item.get('filament_material') or '—'} · {item.get('filament_color') or '—'}")
            grams = html_lib.escape(str(item.get('estimated_grams') or 0))
            number = html_lib.escape(str(item.get('quote_number') or ''))
            rows.append(f'<tr><td><strong>{project}</strong><div class="small text-secondary">{number}</div></td><td>{customer}</td><td><strong>{machine}</strong><div class="small text-secondary">{model}</div></td><td>{filament}</td><td>{grams} g</td></tr>')
        if rows:
            active_box = '<div class="card mb-4"><div class="p-3 border-bottom d-flex justify-content-between"><strong>Imprimindo agora</strong><a href="/printing">Abrir painel de impressão →</a></div><div class="table-responsive"><table class="table mb-0"><thead><tr><th>Projeto</th><th>Cliente</th><th>Máquina</th><th>Filamento</th><th>Estimado</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div></div>'
        else:
            active_box = '<div class="card p-3 mb-4"><div class="d-flex justify-content-between align-items-center"><div><strong>Nenhuma impressão ativa</strong><div class="text-secondary small">Quando iniciar uma impressão, cliente, projeto, máquina e filamento aparecerão aqui.</div></div><a class="btn btn-sm btn-outline-dark" href="/printing">Abrir Impressão</a></div></div>'
        flow_marker = '<div class="card p-4">\n        <h5>Fluxo de produção</h5>'
        if flow_marker in page and 'Abrir painel de impressão' not in page and 'Nenhuma impressão ativa' not in page:
            page = page.replace(flow_marker, active_box + '\n      ' + flow_marker, 1)

    response.set_data(page)
    response.headers['Content-Length'] = str(len(response.get_data()))
    return response
