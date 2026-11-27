"""
Маршруты аутентификации
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required

from admin.models import AdminUser

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    """Страница входа"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = AdminUser.verify_login(username, password)
        
        if user:
            login_user(user)
            from admin import services
            services.log_action('login', summary=request.remote_addr)
            next_page = request.args.get('next')
            # Разрешаем только относительные пути внутри панели (защита от open redirect)
            if not next_page or not next_page.startswith('/') or next_page.startswith('//') or '\\' in next_page:
                next_page = url_for('dashboard.index')
            return redirect(next_page)
        
        flash('Неверное имя пользователя или пароль', 'danger')
    
    return render_template('auth/login.html')


@bp.route('/logout')
@login_required
def logout():
    """Выход из системы"""
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('auth.login'))
