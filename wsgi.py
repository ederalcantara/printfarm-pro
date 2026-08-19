from app import app
from calculator import calculator_bp

app.register_blueprint(calculator_bp)


@app.after_request
def inject_calculator_link(response):
    """Add the calculator link to the existing sidebar without altering app routes."""
    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        return response

    html = response.get_data(as_text=True)
    marker = '<a class="nav-link" href="/catalog" target="_blank">Catálogo público ↗</a>'
    if marker in html and 'href="/calculator"' not in html:
        calculator_link = '<a class="nav-link" href="/calculator">Calculadora</a>\n    '
        html = html.replace(marker, calculator_link + marker, 1)
        response.set_data(html)
        response.headers["Content-Length"] = str(len(response.get_data()))
    return response
