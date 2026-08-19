from app import app
from calculator import calculator_bp

app.register_blueprint(calculator_bp)
