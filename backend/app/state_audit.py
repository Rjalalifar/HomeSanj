"""Private reducer history for replay; this is never part of public inventory."""
from sqlalchemy import JSON, String, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, new_id, utcnow


class StateChange(Base):
    __tablename__ = 'state_changes'
    change_id: Mapped[str] = mapped_column(String, primary_key=True)
    owner_session: Mapped[str] = mapped_column(String, index=True)
    previous: Mapped[dict] = mapped_column(JSON)
    next_state: Mapped[dict] = mapped_column(JSON)
    operations: Mapped[list] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)


def record_change(db, owner, previous, updated, operations, source='form'):
    with db.session.begin() as session:
        session.add(StateChange(change_id=new_id('change'), owner_session=owner,
            previous=previous.model_dump(mode='json'), next_state=updated.model_dump(mode='json'),
            operations=[op.model_dump() for op in operations], source=source, created_at=utcnow()))
