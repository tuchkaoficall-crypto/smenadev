"""
Справочник городов: используется при регистрации работников, в форме заявки,
в рассылках вакансий и фильтрах панели. Бот подхватывает изменения в течение минуты.
"""
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required

from admin import db_session, get_or_404
from admin import growth
from admin.services import LifecycleError
from database.models import City

bp = Blueprint('cities', __name__, url_prefix='/cities')


@bp.route('/')
@login_required
def index():
    cities = db_session.query(City).order_by(City.sort_order, City.name).all()
    workers, orders, active = growth.city_usage()
    known = {c.name for c in cities}
    unknown = sorted((set(workers) | set(orders)) - known - {None, ''})
    return render_template('cities/index.html', cities=cities, workers=workers, orders=orders,
                           active=active, unknown=unknown)


def _run(fn, msg, *args):
    try:
        fn(*args)
        flash(msg, 'success')
    except LifecycleError as e:
        db_session.rollback()
        flash(str(e), 'warning')
    return redirect(url_for('cities.index'))


@bp.route('/add', methods=['POST'])
@login_required
def add():
    name = request.form.get('name')
    return _run(growth.add_city, f'Город «{(name or "").strip()}» добавлен. В боте он появится в течение минуты',
                name)


@bp.route('/<int:city_id>/toggle', methods=['POST'])
@login_required
def toggle(city_id):
    city = get_or_404(City, city_id)
    return _run(growth.toggle_city, 'Готово', city)


@bp.route('/<int:city_id>/rename', methods=['POST'])
@login_required
def rename(city_id):
    city = get_or_404(City, city_id)
    return _run(growth.rename_city, 'Город переименован, работники и заказы обновлены',
                city, request.form.get('name'))


@bp.route('/<int:city_id>/move/<direction>', methods=['POST'])
@login_required
def move(city_id, direction):
    city = get_or_404(City, city_id)
    growth.move_city(city, -1 if direction == 'up' else 1)
    return redirect(url_for('cities.index'))
