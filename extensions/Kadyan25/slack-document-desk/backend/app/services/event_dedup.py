from sqlalchemy.exc import IntegrityError

from app.db.models import ProcessedSlackEvent


def claim_event(db, event_id: str) -> bool:
    """Atomically claims a Slack event_id via the column's unique constraint — first
    delivery wins. Returns False if already claimed (a Slack retry of the same
    delivery, same event_id every time), so the caller knows to skip all side effects
    rather than repeat them."""
    try:
        db.add(ProcessedSlackEvent(event_id=event_id))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False
