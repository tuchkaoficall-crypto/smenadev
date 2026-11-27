"""
Управление работниками: поиск/фильтры, CSV, профиль с историей, бан и разбан
"""
import json
import mimetypes
from datetime import datetime

from flask import Blueprint, render_template, request, flash, redirect, url_for, abort, make_response
from flask_login import login_required
from sqlalchemy import or_

from admin import db_session, get_or_404
from admin import services, telegram, growth
from admin.services import LifecycleError
from database.models import Worker, User, Review, WorkerPenalty, WorkerDocument, ShiftCheckin
from config import JOB_CATEGORIES, ResponseStatus, PENALTY_POINTS

bp = Blueprint('workers', __name__, url_prefix='/workers')

SORTS = {
    "rating": (Worker.rating.desc(), Worker.total_reviews.desc()),
    "shifts": (Worker.completed_shifts.desc(),),
    "new": (Worker.created_at.desc(),),
}


def _categories(worker):
    try:
        return json.loads(worker.categories) if worker.categories else []
    except (ValueError, TypeError):
        return []


def _filtered():
    args = request.args
    query = db_session.query(Worker).join(User, Worker.user_id == User.id)
    if args.get('city'):
        query = query.filter(Worker.city == args['city'])
    q = (args.get('q') or '').strip()
    if q:
        like = f"%{q}%"
        conds = [User.first_name.ilike(like), User.last_name.ilike(like),
                 User.username.ilike(like.lstrip('@')), User.phone.ilike(like)]
        if q.isdigit():
            conds.append(Worker.user_id == int(q))
        query = query.filter(or_(*conds))
    if args.get('blocked') == '1':
        query = query.filter(User.is_blocked.is_(True))
    elif args.get('blocked') == '0':
        query = query.filter(or_(User.is_blocked.is_(False), User.is_blocked.is_(None)))
    min_rating = args.get('min_rating', type=float)
    if min_rating:
        query = query.filter(Worker.rating >= min_rating)
    if args.get('verified') == '1':
        query = query.filter(Worker.verified_at.isnot(None))
    elif args.get('verified') == '0':
        query = query.filter(Worker.verified_at.is_(None))
    workers = query.order_by(*SORTS.get(args.get('sort'), SORTS['rating'])).all()
    category = args.get('category')
    if category:
        # Пустой список категорий = «любая работа»
        workers = [w for w in workers if not _categories(w) or category in _categories(w)]
    return workers


@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 25
    workers = _filtered()
    total = len(workers)
    cities = growth.all_city_names()
    rel_filter = request.args.get('reliability')
    if rel_filter:
        rel_all = growth.reliability_map(workers)
        workers = [w for w in workers if rel_all[w.id]['level']['code'] == rel_filter
                   or (rel_filter == 'priority' and rel_all[w.id]['priority'])]
        total = len(workers)
    page_workers = workers[(page - 1) * per_page: page * per_page]
    return render_template(
        'workers/index.html',
        workers=page_workers, rel=growth.reliability_map(page_workers),
        cats={w.id: _categories(w) for w in workers},
        page=page, total=total, total_pages=(total + per_page - 1) // per_page,
        city=request.args.get('city'), cities=cities, categories=JOB_CATEGORIES,
        args={k: v for k, v in request.args.items() if k != 'page'},
    )


@bp.route('/export.csv')
@login_required
def export_csv():
    rows = []
    workers = _filtered()
    from services import reliability as R
    points = R.points_map_sync(db_session, [w.id for w in workers])
    for w in workers:
        u = w.user
        rows.append([w.id, u.full_name if u else '', f"@{u.username}" if u and u.username else '',
                     u.phone if u else '', w.user_id, w.city, ", ".join(_categories(w)) or 'Любая',
                     round(w.rating or 0, 2), w.total_reviews, w.completed_shifts,
                     'да' if u and u.is_blocked else 'нет', services.fmt_dt(w.created_at),
                     points.get(w.id, 0), 'да' if w.verified_at else 'нет'])
    return services.csv_response(
        f"workers_{datetime.now():%Y%m%d_%H%M}.csv",
        ["ID", "Имя", "Telegram", "Телефон", "Telegram ID", "Город", "Категории", "Рейтинг",
         "Отзывов", "Смен", "Заблокирован", "Регистрация", "Штрафные баллы", "Документы проверены"],
        rows,
    )


@bp.route('/<int:worker_id>')
@login_required
def detail(worker_id):
    worker = get_or_404(Worker, worker_id)
    reviews = db_session.query(Review).filter(Review.worker_id == worker_id).order_by(Review.created_at.desc()).all()
    responses = sorted(worker.responses, key=lambda r: r.created_at or datetime.min, reverse=True)
    stats = {
        "responses": len(responses),
        "confirmed": sum(1 for r in responses if r.status in (ResponseStatus.CONFIRMED, ResponseStatus.COMPLETED)),
        "completed": sum(1 for r in responses if r.status == ResponseStatus.COMPLETED),
        "rejected": sum(1 for r in responses if r.status == ResponseStatus.REJECTED),
        "withdrawn": sum(1 for r in responses if r.status == ResponseStatus.WITHDRAWN),
        "no_show": sum(1 for r in responses if r.status == ResponseStatus.NO_SHOW),
        "earned": sum(r.order.shift_amount for r in responses
                      if r.status == ResponseStatus.COMPLETED and r.order),
    }
    stats["conversion"] = round(stats["confirmed"] / stats["responses"] * 100) if stats["responses"] else None
    return render_template(
        'workers/detail.html',
        worker=worker, reviews=reviews, categories=_categories(worker), responses=responses,
        stats=stats, history=services.entity_history('worker', worker.id),
        rel=growth.reliability_info(worker),
        penalties=db_session.query(WorkerPenalty).filter(WorkerPenalty.worker_id == worker.id)
        .order_by(WorkerPenalty.created_at.desc()).all(),
        documents=db_session.query(WorkerDocument).filter(WorkerDocument.worker_id == worker.id)
        .order_by(WorkerDocument.created_at.desc()).all(),
        checkins={c.response_id: c for c in db_session.query(ShiftCheckin).filter(
            ShiftCheckin.worker_id == worker.id)},
        penalty_kinds=PENALTY_POINTS,
    )


@bp.route('/<int:worker_id>/ban', methods=['POST'])
@login_required
def ban(worker_id):
    worker = get_or_404(Worker, worker_id)
    reason = (request.form.get('reason') or '').strip()
    worker.user.is_blocked = True
    services.log_action('user_ban', 'worker', worker.id, reason or None, commit=False)
    db_session.commit()
    if request.form.get('notify'):
        telegram.send_message(worker.user_id, "❌ Ваш аккаунт заблокирован администратором."
                              + (f"\n\nПричина: {reason}" if reason else ""))
    flash('Работник заблокирован', 'danger')
    return redirect(url_for('workers.detail', worker_id=worker_id))


@bp.route('/<int:worker_id>/unban', methods=['POST'])
@login_required
def unban(worker_id):
    worker = get_or_404(Worker, worker_id)
    worker.user.is_blocked = False
    services.log_action('user_unban', 'worker', worker.id, commit=False)
    db_session.commit()
    flash('Работник разблокирован', 'success')
    return redirect(url_for('workers.detail', worker_id=worker_id))


@bp.route('/<int:worker_id>/note', methods=['POST'])
@login_required
def note(worker_id):
    get_or_404(Worker, worker_id)
    text = (request.form.get('text') or '').strip()
    if text:
        services.log_action('note', 'worker', worker_id, text)
        flash('Заметка добавлена', 'success')
    return redirect(url_for('workers.detail', worker_id=worker_id))


# ==== Надёжность: штрафные баллы ====

@bp.route('/<int:worker_id>/penalty', methods=['POST'])
@login_required
def penalty_add(worker_id):
    worker = get_or_404(Worker, worker_id)
    kind = request.form.get('kind') or 'manual'
    points = request.form.get('points', type=int)
    reason = (request.form.get('reason') or '').strip() or None
    try:
        growth.add_penalty(worker, kind, points, reason, notify=bool(request.form.get('notify')))
        flash('Штрафные баллы начислены', 'warning')
    except LifecycleError as e:
        db_session.rollback()
        flash(str(e), 'warning')
    return redirect(url_for('workers.detail', worker_id=worker_id) + '#reliability')


@bp.route('/penalties/<int:penalty_id>/cancel', methods=['POST'])
@login_required
def penalty_cancel(penalty_id):
    penalty = get_or_404(WorkerPenalty, penalty_id)
    try:
        growth.cancel_penalty(penalty)
        flash('Штраф аннулирован', 'success')
    except LifecycleError as e:
        db_session.rollback()
        flash(str(e), 'warning')
    return redirect(url_for('workers.detail', worker_id=penalty.worker_id) + '#reliability')


# ==== Документы ====

@bp.route('/documents/<int:doc_id>/file')
@login_required
def document_file(doc_id):
    """Показать файл документа (скачивается из Telegram по file_id, у нас не хранится)"""
    doc = get_or_404(WorkerDocument, doc_id)
    data, path = telegram.get_file(doc.file_id)
    if data is None:
        abort(404, description="Не удалось получить файл из Telegram")
    mime = doc.mime_type or mimetypes.guess_type(path or '')[0] or 'application/octet-stream'
    resp = make_response(data)
    resp.headers['Content-Type'] = mime
    resp.headers['Cache-Control'] = 'private, max-age=300'
    resp.headers['X-Content-Type-Options'] = 'nosniff'
    if not mime.startswith('image/') and mime != 'application/pdf':
        resp.headers['Content-Disposition'] = f'attachment; filename=document_{doc.id}'
    return resp


@bp.route('/documents/<int:doc_id>/<action>', methods=['POST'])
@login_required
def document_review(doc_id, action):
    doc = get_or_404(WorkerDocument, doc_id)
    back = services.safe_next(url_for('workers.detail', worker_id=doc.worker_id) + '#documents')
    if action not in ('approve', 'reject'):
        abort(404)
    try:
        growth.review_document(doc, action == 'approve', (request.form.get('reason') or '').strip() or None)
        flash('Документ подтверждён' if action == 'approve' else 'Документ отклонён, работник уведомлён',
              'success' if action == 'approve' else 'warning')
    except LifecycleError as e:
        db_session.rollback()
        flash(str(e), 'warning')
    return redirect(back)


@bp.route('/<int:worker_id>/unverify', methods=['POST'])
@login_required
def unverify(worker_id):
    worker = get_or_404(Worker, worker_id)
    growth.revoke_verification(worker)
    flash('Отметка «документы проверены» снята', 'warning')
    return redirect(url_for('workers.detail', worker_id=worker_id) + '#documents')
