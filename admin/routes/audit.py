"""
Журнал действий администраторов
"""
from datetime import datetime

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import or_

from admin import db_session
from admin import services
from database.models import AdminAction

bp = Blueprint('audit', __name__, url_prefix='/audit')


def _query():
    q = db_session.query(AdminAction)
    if request.args.get('action'):
        q = q.filter(AdminAction.action == request.args['action'])
    if request.args.get('entity'):
        q = q.filter(AdminAction.entity_type == request.args['entity'])
    s = (request.args.get('q') or '').strip()
    if s:
        conds = [AdminAction.summary.ilike(f"%{s}%")]
        if s.isdigit():
            conds.append(AdminAction.entity_id == int(s))
        q = q.filter(or_(*conds))
    return q.order_by(AdminAction.created_at.desc())


@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    q = _query()
    total = q.count()
    return render_template(
        'audit/index.html', actions=q.offset((page - 1) * per_page).limit(per_page).all(),
        page=page, total=total, total_pages=(total + per_page - 1) // per_page,
        args={k: v for k, v in request.args.items() if k != 'page'},
    )


@bp.route('/export.csv')
@login_required
def export_csv():
    rows = [[a.id, services.fmt_dt(a.created_at), a.admin or '', services.ACTION_NAMES.get(a.action, a.action),
             a.entity_type or '', a.entity_id or '', a.summary or ''] for a in _query().all()]
    return services.csv_response(f"audit_{datetime.now():%Y%m%d_%H%M}.csv",
                                 ["ID", "Время (UTC)", "Админ", "Действие", "Объект", "ID объекта", "Описание"], rows)
