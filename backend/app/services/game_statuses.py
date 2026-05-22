from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import GameStatus

logger = logging.getLogger(__name__)

REQUIRED_GAME_STATUSES: tuple[tuple[str, str], ...] = (
    ('SCHEDULED', 'Scheduled'),
    ('COMPLETED', 'Completed'),
    ('CANCELLED', 'Cancelled'),
    ('POSTPONED', 'Postponed'),
    ('FORFEIT', 'Forfeit'),
)


def ensure_required_game_statuses(db: Session) -> list[str]:
    created_or_updated: list[str] = []
    for code, label in REQUIRED_GAME_STATUSES:
        exact = db.query(GameStatus).filter(GameStatus.code == code).first()
        if exact:
            if not exact.is_active or exact.label != label:
                exact.is_active = True
                exact.label = label
                created_or_updated.append(code)
            continue

        existing = db.query(GameStatus).filter(GameStatus.code.ilike(code)).order_by(GameStatus.created_at.asc()).first()
        if existing:
            existing.code = code
            existing.label = label
            existing.is_active = True
            created_or_updated.append(code)
            continue

        db.add(GameStatus(code=code, label=label, is_active=True))
        created_or_updated.append(code)
    return created_or_updated


def seed_required_game_statuses(db: Session) -> None:
    try:
        changed = ensure_required_game_statuses(db)
        db.commit()
        if changed:
            logger.info('Game status seed complete. Ensured statuses: %s', ', '.join(changed))
        else:
            logger.info('Game status seed noop: all required statuses already present.')
    except SQLAlchemyError:
        db.rollback()
        logger.exception('Game status seed failed due to database error.')

