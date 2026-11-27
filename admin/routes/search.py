"""
Глобальный поиск по заказам, работодателям и работникам
"""
from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import login_required
from sqlalchemy import or_

from admin import db_session
from database.models import Order, Employer, Worker, User

bp = Blueprint('search', __name__, url_prefix='/search')


@bp.route('/')
@login_required
def index():
    q = (request.args.get('q') or '').strip()
    if not q:
        return redirect(url_for('dashboard.index'))
    like = f"%{q.lstrip('@#')}%"
    num = int(q.lstrip('#')) if q.lstrip('#').isdigit() else None

    order_conds = [Order.address.ilike(like), Order.description.ilike(like), Order.category.ilike(like)]
    if num is not None:
        order_conds.append(Order.id == num)
    orders = db_session.query(Order).filter(or_(*order_conds)).order_by(Order.created_at.desc()).limit(20).all()

    emp_conds = [Employer.company_name.ilike(like), Employer.contact_person.ilike(like),
                 Employer.contact_phone.ilike(like), Employer.inn.ilike(like)]
    if num is not None:
        emp_conds += [Employer.user_id == num, Employer.id == num]
    employers = db_session.query(Employer).filter(or_(*emp_conds)).limit(20).all()

    w_conds = [User.first_name.ilike(like), User.last_name.ilike(like), User.username.ilike(like), User.phone.ilike(like)]
    if num is not None:
        w_conds += [Worker.user_id == num, Worker.id == num]
    workers = db_session.query(Worker).join(User, Worker.user_id == User.id).filter(or_(*w_conds)).limit(20).all()

    # Точное совпадение номера заказа — сразу открываем
    if q.startswith('#') and num is not None and len(orders) and orders[0].id == num and not employers and not workers:
        return redirect(url_for('orders.detail', order_id=num))
    return render_template('search/index.html', q=q, orders=orders, employers=employers, workers=workers)
