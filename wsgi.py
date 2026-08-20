from app import app
from calculator import calculator_bp
from customer_portal import portal_bp
from online_requests import online_bp

app.register_blueprint(calculator_bp)
app.register_blueprint(portal_bp)
app.register_blueprint(online_bp)


@app.after_request
def inject_sidebar_links(response):
    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        return response

    html = response.get_data(as_text=True)
    marker = '<a class="nav-link" href="/catalog" target="_blank">Catálogo público ↗</a>'
    additions = ''
    if 'href="/online-requests"' not in html:
        additions += '<a class="nav-link" href="/online-requests">Pedidos Online</a>\n    '
    if 'href="/calculator"' not in html:
        additions += '<a class="nav-link" href="/calculator">Calculadora</a>\n    '
    if marker in html and additions:
        html = html.replace(marker, additions + marker, 1)
        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))
    return response
