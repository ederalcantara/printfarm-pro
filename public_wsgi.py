from flask import redirect, request, session

from wsgi import app
from public_site import public_site_bp

app.register_blueprint(public_site_bp)


@app.before_request
def public_home_for_visitors():
    # Keep the owner's authenticated dashboard at /. Visitors see the public site.
    if request.path == '/' and not session.get('user_id'):
        return redirect('/home')
