"""
Рассылки сообщений пользователям через бота
"""
import json

from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify
from flask_login import login_required, current_user

from admin import db_session, get_or_404
from admin import services
from database.models import Broadcast, Worker
from config import JOB_CATEGORIES

bp = Blueprint('broadcasts', __name__, url_prefix='/broadcasts')

AUDIENCES = {"all": "Все пользователи", "workers": "Работники", "employers": "Работодатели (одобренные)"}
MAX_LEN = 4000


def _params(src):
    audience = src.get('audience', 'workers')
    if audience not in AUDIENCES:
        audience = 'workers'
    city = (src.get('city') or '').strip() or None
    category = (src.get('category') or '').strip() or None
    return audience, city, category


@bp.route('/')
@login_required
def index():
    broadcasts = db_session.query(Broadcast).order_by(Broadcast.created_at.desc()).limit(50).all()
    from admin import growth
    cities = growth.all_city_names()
    return render_template('broadcasts/index.html', broadcasts=broadcasts, audiences=AUDIENCES,
                           cities=cities, categories=JOB_CATEGORIES, max_len=MAX_LEN)


@bp.route('/count')
@login_required
def count():
    audience, city, category = _params(request.args)
    return jsonify(count=len(services.broadcast_recipients(db_session, audience, city, category)))


@bp.route('/send', methods=['POST'])
@login_required
def send():
    text = (request.form.get('text') or '').strip()
    if not text:
        flash('Введите текст сообщения', 'warning')
        return redirect(url_for('broadcasts.index'))
    if len(text) > MAX_LEN:
        flash(f'Сообщение длиннее {MAX_LEN} символов', 'warning')
        return redirect(url_for('broadcasts.index'))
    audience, city, category = _params(request.form)
    recipients = services.broadcast_recipients(db_session, audience, city, category)
    if not recipients:
        flash('Нет получателей под выбранные условия', 'warning')
        return redirect(url_for('broadcasts.index'))
    b = Broadcast(admin=current_user.username, audience=audience, text=text, total=len(recipients),
                  filters=json.dumps({"city": city, "category": category}, ensure_ascii=False))
    db_session.add(b)
    db_session.commit()
    services.log_action('broadcast', 'broadcast', b.id, f"{AUDIENCES[audience]}: {len(recipients)} получателей")
    services.run_broadcast_async(b.id, recipients, text)
    flash(f'Рассылка #{b.id} запущена: {len(recipients)} получателей', 'success')
    return redirect(url_for('broadcasts.index'))


@bp.route('/<int:broadcast_id>/status')
@login_required
def status(broadcast_id):
    b = get_or_404(Broadcast, broadcast_id)
    db_session.refresh(b)
    return jsonify(status=b.status, sent=b.sent, failed=b.failed, total=b.total)
