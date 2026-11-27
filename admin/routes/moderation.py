"""
Очередь модерации: анкеты работодателей, заявки и отклики в одном месте
"""
from flask import Blueprint, render_template
from flask_login import login_required

from admin import db_session
from admin import services
from database.models import Employer, Order, Response
from config import EmployerStatus, ResponseStatus

bp = Blueprint('moderation', __name__, url_prefix='/moderation')


@bp.route('/')
@login_required
def index():
    employers = db_session.query(Employer).filter(
        Employer.status == EmployerStatus.PENDING).order_by(Employer.created_at.asc()).all()
    orders = db_session.query(Order).filter(
        Order.status.in_(services.MODERATION_STATUSES)).order_by(Order.created_at.asc()).all()
    responses = db_session.query(Response).filter(
        Response.status.in_((ResponseStatus.PENDING, ResponseStatus.CONTACTED))
    ).order_by(Response.created_at.asc()).all()
    # Отклики только по заказам, где ещё идёт набор
    responses = [r for r in responses if r.order and r.order.status not in services.FINAL_STATUSES]
    from admin import growth
    return render_template(
        'moderation/index.html', employers=employers, orders=orders, responses=responses,
        documents=growth.pending_documents(),
        confirmed={r.order_id: services.confirmed_count(r.order) for r in responses},
    )
