"""
Админ-логика для надёжности работников, документов, отметок на смене,
реферальной программы и справочника городов.
"""
from datetime import datetime

from flask_login import current_user

from admin import db_session
from admin.services import log_action, LifecycleError, _notify, _worker_name
from config import (
    ResponseStatus, OrderStatus, DOCUMENT_TYPES, PENALTY_NAMES, PENALTY_POINTS, REFERRAL_STATUS_NAMES,
)
from database.models import (
    Worker, WorkerDocument, ShiftCheckin, Referral, City, Order, User, Employer,
)
from services import reliability as R


def _admin():
    return getattr(current_user, "username", None) or "admin"


# ==== Надёжность ====

def reliability_info(worker):
    points = R.worker_points_sync(db_session, worker.id)
    return {"points": points, "level": R.level(points), "priority": R.is_priority(worker, points),
            "restricted": R.is_restricted(points)}


def reliability_map(workers):
    points = R.points_map_sync(db_session, [w.id for w in workers])
    return {w.id: {"points": points.get(w.id, 0), "level": R.level(points.get(w.id, 0)),
                   "priority": R.is_priority(w, points.get(w.id, 0))} for w in workers}


def add_penalty(worker, kind, points=None, reason=None, order_id=None, notify=True):
    if kind not in PENALTY_POINTS:
        raise LifecycleError("Неизвестный тип штрафа")
    if points is not None and not (1 <= points <= 20):
        raise LifecycleError("Баллы должны быть от 1 до 20")
    p = R.new_penalty(worker.id, kind, order_id=order_id, points=points, reason=reason, actor=_admin())
    db_session.add(p)
    log_action("penalty_add", "worker", worker.id,
               f"+{p.points} б.: {PENALTY_NAMES.get(kind, kind)}" + (f" — {reason}" if reason else ""), commit=False)
    db_session.commit()
    if notify:
        total = R.worker_points_sync(db_session, worker.id)
        _notify(worker.user_id, R.penalty_text(kind, p.points, total, order_id))
    return p


def cancel_penalty(penalty):
    if penalty.is_cancelled:
        raise LifecycleError("Штраф уже аннулирован")
    penalty.is_cancelled = True
    penalty.cancelled_at = datetime.utcnow()
    penalty.cancelled_by = _admin()
    log_action("penalty_cancel", "worker", penalty.worker_id,
               f"−{penalty.points} б.: {PENALTY_NAMES.get(penalty.kind, penalty.kind)}", commit=False)
    db_session.commit()
    _notify(penalty.worker.user_id, f"✅ Администратор аннулировал штраф ({penalty.points} б.): "
                                    f"{PENALTY_NAMES.get(penalty.kind, penalty.kind)}.")


def mark_no_show(response, reason=None):
    """Работник не вышел: отклик -> no_show, +5 баллов. Можно и после завершения смены"""
    order = response.order
    if response.status not in (ResponseStatus.CONFIRMED, ResponseStatus.COMPLETED):
        raise LifecycleError("Неявку можно отметить только у подтверждённого работника")
    if order.shift_date > datetime.now():
        raise LifecycleError("Смена ещё не началась")
    was_completed = response.status == ResponseStatus.COMPLETED
    response.status = ResponseStatus.NO_SHOW
    response.admin_comment = reason or "Не вышел на смену"
    worker = response.worker
    if was_completed and (worker.completed_shifts or 0) > 0:
        worker.completed_shifts -= 1
    db_session.add(R.new_penalty(worker.id, "no_show", order_id=order.id, reason=reason, actor=_admin()))
    log_action("response_no_show", "order", order.id, _worker_name(worker) + (f": {reason}" if reason else ""),
               commit=False)
    db_session.commit()
    total = R.worker_points_sync(db_session, worker.id)
    _notify(worker.user_id, R.penalty_text("no_show", PENALTY_POINTS["no_show"], total, order.id))
    return total


def order_checkins(order):
    return db_session.query(ShiftCheckin).filter(ShiftCheckin.order_id == order.id).order_by(
        ShiftCheckin.created_at).all()


def set_order_point(order, raw: str):
    """«61.7849, 34.3469» или ссылка на Яндекс/Google-карты -> координаты заказа"""
    import re
    raw = (raw or "").strip()
    if not raw:
        order.latitude = order.longitude = None
        log_action("order_point", "order", order.id, "Точка на карте удалена", commit=False)
        db_session.commit()
        return None
    nums = [float(x) for x in re.findall(r"-?\d{1,3}\.\d+", raw)]
    if len(nums) < 2:
        raise LifecycleError("Укажите координаты в виде «61.7849, 34.3469»")
    lat, lon = nums[0], nums[1]
    if "yandex" in raw and ("ll=" in raw or "pt=" in raw):
        lon, lat = nums[0], nums[1]  # в ссылках Яндекса сначала долгота
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise LifecycleError("Координаты вне допустимого диапазона")
    order.latitude, order.longitude = lat, lon
    log_action("order_point", "order", order.id, f"{lat:.5f}, {lon:.5f}", commit=False)
    db_session.commit()
    return lat, lon


# ==== Документы ====

def pending_documents():
    return db_session.query(WorkerDocument).filter(WorkerDocument.status == "pending").order_by(
        WorkerDocument.created_at).all()


def review_document(doc, approve: bool, reason=None):
    if doc.status != "pending":
        raise LifecycleError("Документ уже проверен")
    doc.status = "approved" if approve else "rejected"
    doc.reject_reason = None if approve else (reason or "Документ не читается")
    doc.reviewed_at = datetime.utcnow()
    doc.reviewed_by = _admin()
    worker = doc.worker
    if approve and doc.doc_type == "passport" and not worker.verified_at:
        worker.verified_at = datetime.utcnow()
    name = DOCUMENT_TYPES.get(doc.doc_type, doc.doc_type)
    log_action("document_approve" if approve else "document_reject", "worker", worker.id,
               name + ("" if approve else f": {doc.reject_reason}"), commit=False)
    db_session.commit()
    if approve:
        text = f"✅ Документ «{name}» проверен."
        if doc.doc_type == "passport":
            text += " В профиле появилась отметка «Документы проверены», вакансии будут приходить вам первыми."
    else:
        text = (f"❌ Документ «{name}» не принят.\nПричина: {doc.reject_reason}\n\n"
                "Загрузите новое фото: «👤 Мой профиль» → «🪪 Подтвердить документы».")
    _notify(worker.user_id, text)


def revoke_verification(worker):
    worker.verified_at = None
    log_action("verification_revoke", "worker", worker.id, commit=False)
    db_session.commit()


# ==== Рефералы ====

def referral_rows(status=None):
    q = db_session.query(Referral)
    if status:
        q = q.filter(Referral.status == status)
    refs = q.order_by(Referral.created_at.desc()).all()
    ids = {r.referrer_id for r in refs} | {r.referred_id for r in refs}
    users = {u.id: u for u in db_session.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    workers = {w.user_id: w for w in db_session.query(Worker).filter(Worker.user_id.in_(ids)).all()} if ids else {}
    employers = {e.user_id: e for e in db_session.query(Employer).filter(Employer.user_id.in_(ids)).all()} if ids else {}
    return refs, users, workers, employers


def referral_stats():
    refs = db_session.query(Referral).all()
    by_ref = {}
    for r in refs:
        by_ref.setdefault(r.referrer_id, []).append(r)
    top = sorted(by_ref.items(), key=lambda kv: (-sum(1 for r in kv[1] if r.status in ("qualified", "paid")),
                                                 -len(kv[1])))[:10]
    return {
        "total": len(refs),
        "qualified": sum(1 for r in refs if r.status in ("qualified", "paid")),
        "to_pay": sum(r.bonus_amount or 0 for r in refs if r.status == "qualified"),
        "paid": sum(r.bonus_amount or 0 for r in refs if r.status == "paid"),
        "top": top,
    }


def referral_set_status(ref, status, comment=None):
    if status not in REFERRAL_STATUS_NAMES:
        raise LifecycleError("Неверный статус")
    if status == "paid" and ref.status != "qualified":
        raise LifecycleError("Выплатить можно только начисленный бонус")
    old = ref.status
    ref.status = status
    if comment:
        ref.comment = comment
    if status == "paid":
        ref.paid_at = datetime.utcnow()
    log_action("referral_" + status, "referral", ref.id,
               f"{REFERRAL_STATUS_NAMES.get(old, old)} → {REFERRAL_STATUS_NAMES[status]}"
               + (f": {comment}" if comment else ""), commit=False)
    db_session.commit()
    if status == "paid":
        _notify(ref.referrer_id, f"💰 Бонус {ref.bonus_amount or 0:.0f} ₽ за приглашённого друга выплачен. Спасибо!")


# ==== Города ====

def city_usage():
    from sqlalchemy import func
    workers = dict(db_session.query(Worker.city, func.count(Worker.id)).group_by(Worker.city).all())
    orders = dict(db_session.query(Order.city, func.count(Order.id)).group_by(Order.city).all())
    active = dict(db_session.query(Order.city, func.count(Order.id)).filter(
        Order.status.in_((OrderStatus.SEARCH_WORKERS, OrderStatus.CONFIRM_WORKERS, OrderStatus.PREPAYMENT,
                          OrderStatus.SHIFT_STARTED))).group_by(Order.city).all())
    return workers, orders, active


def add_city(name):
    name = " ".join((name or "").split())
    if not name or len(name) > 60:
        raise LifecycleError("Введите название города (до 60 символов)")
    if len(f"wcity:{name}".encode()) > 64:
        raise LifecycleError("Слишком длинное название для кнопки в Telegram")
    if db_session.query(City).filter(City.name == name).first():
        raise LifecycleError("Такой город уже есть")
    max_sort = max([c.sort_order for c in db_session.query(City).all()] or [0])
    city = City(name=name, is_active=True, sort_order=max_sort + 1)
    db_session.add(city)
    log_action("city_add", "city", None, name, commit=False)
    db_session.commit()
    return city


def toggle_city(city):
    if city.is_active and db_session.query(City).filter(City.is_active.is_(True)).count() <= 1:
        raise LifecycleError("Должен остаться хотя бы один активный город")
    city.is_active = not city.is_active
    log_action("city_toggle", "city", city.id, f"{city.name}: {'включён' if city.is_active else 'выключен'}",
               commit=False)
    db_session.commit()


def rename_city(city, new_name):
    """Переименовать город и обновить его у работников и заказов (строки в БД)"""
    new_name = " ".join((new_name or "").split())
    if not new_name or len(new_name) > 60:
        raise LifecycleError("Введите название города (до 60 символов)")
    if new_name == city.name:
        return 0
    if db_session.query(City).filter(City.name == new_name).first():
        raise LifecycleError("Такой город уже есть")
    old = city.name
    n = db_session.query(Worker).filter(Worker.city == old).update({Worker.city: new_name})
    n += db_session.query(Order).filter(Order.city == old).update({Order.city: new_name})
    city.name = new_name
    log_action("city_rename", "city", city.id, f"{old} → {new_name} (записей: {n})", commit=False)
    db_session.commit()
    return n


def move_city(city, delta):
    cities = db_session.query(City).order_by(City.sort_order, City.name).all()
    i = cities.index(city)
    j = i + delta
    if 0 <= j < len(cities):
        cities[i], cities[j] = cities[j], cities[i]
        for k, c in enumerate(cities):
            c.sort_order = k
        db_session.commit()


def all_city_names():
    """Для фильтров: города из справочника + встречающиеся в данных"""
    from services.cities import list_sync
    names = list_sync(db_session, active_only=False)
    extra = {c for (c,) in db_session.query(Worker.city).distinct() if c} | \
            {c for (c,) in db_session.query(Order.city).distinct() if c}
    return names + sorted(extra - set(names))

