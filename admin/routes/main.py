"""
Главные маршруты
"""
from flask import Blueprint, redirect, url_for
from flask_login import login_required

bp = Blueprint('main', __name__)


@bp.route('/')
@login_required
def index():
    """Главная страница перенаправляет на дашборд"""
    return redirect(url_for('dashboard.index'))
