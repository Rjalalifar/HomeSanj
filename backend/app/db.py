"""SQLAlchemy 2 persistence with additive, versioned SQLite migrations."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Float, Integer, String, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f'{prefix}_{uuid4().hex}'


class Base(DeclarativeBase):
    pass


class Migration(Base):
    __tablename__ = 'schema_migrations'
    version: Mapped[int] = mapped_column(primary_key=True)
    applied_at: Mapped[str] = mapped_column(String)


class Listing(Base):
    __tablename__ = 'listings'
    property_id: Mapped[str] = mapped_column(String, primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String, index=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean)
    deposit_toman: Mapped[int | None] = mapped_column(Integer, index=True)
    monthly_rent_toman: Mapped[int | None] = mapped_column(Integer, index=True)
    area_m2: Mapped[float | None] = mapped_column(Float)
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    parking: Mapped[bool | None] = mapped_column(Boolean)
    elevator: Mapped[bool | None] = mapped_column(Boolean)
    payload: Mapped[dict] = mapped_column(JSON)


class Task(Base):
    __tablename__ = 'tasks'
    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    destination: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String)


class SearchRequest(Base):
    __tablename__ = 'search_requests'
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    parent_request_id: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot_id: Mapped[str] = mapped_column(String, unique=True)
    state: Mapped[dict] = mapped_column(JSON)
    versions: Mapped[dict] = mapped_column(JSON)
    candidate_count: Mapped[int] = mapped_column(Integer)
    evaluated_count: Mapped[int] = mapped_column(Integer, default=0)
    completion_status: Mapped[str] = mapped_column(String, index=True)
    subset_method: Mapped[str] = mapped_column(String)
    batch_limit: Mapped[int] = mapped_column(Integer)
    warnings: Mapped[list] = mapped_column(JSON)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[str] = mapped_column(String)


class Candidate(Base):
    __tablename__ = 'snapshot_candidates'
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    property_id: Mapped[str] = mapped_column(String, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    property_snapshot: Mapped[dict] = mapped_column(JSON)
    property_verdicts: Mapped[list] = mapped_column(JSON)
    accessibility_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class Evaluation(Base):
    __tablename__ = 'route_evaluations'
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    property_id: Mapped[str] = mapped_column(String, primary_key=True)
    cache_key: Mapped[str] = mapped_column(String)
    result: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String)


class RouteCache(Base):
    __tablename__ = 'route_cache'
    cache_key: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[float] = mapped_column(Float)


class ProviderCall(Base):
    __tablename__ = 'provider_calls'
    call_id: Mapped[str] = mapped_column(String, primary_key=True)
    day: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    reserved_tokens: Mapped[int] = mapped_column(Integer)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(String)


class Database:
    def __init__(self, url: str):
        if url.startswith('sqlite:///') and ':memory:' not in url:
            Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
        options = {'connect_args': {'check_same_thread': False, 'timeout': 30}} if url.startswith('sqlite') else {}
        if ':memory:' in url:
            options['poolclass'] = StaticPool
        self.engine = create_engine(url, **options)
        if url.startswith('sqlite'):
            @event.listens_for(self.engine, 'connect')
            def configure(connection, _):
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('PRAGMA journal_mode=WAL')
        self.session = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self):
        # Import additive feature models before applying idempotent migrations.
        from . import catalog, session as browser_sessions, state_audit, feedback, evaluation_store, release_control
        Base.metadata.create_all(self.engine)
        with self.session.begin() as session:
            if session.get(Migration, 1) is None:
                session.add(Migration(version=1, applied_at=utcnow()))
        catalog.migrate_catalog(self)
        feedback.migrate_feedback(self)
        evaluation_store.migrate_evaluation(self)
        from .accessibility import migrate_accessibility
        migrate_accessibility(self)

    def insert_listings(self, listings: list[dict]) -> dict:
        from .contracts import PropertyListing
        inserted = skipped = 0
        with self.session.begin() as session:
            for raw in listings:
                item = PropertyListing.model_validate(raw).model_dump(mode='json')
                if session.get(Listing, item['property_id']) is not None:
                    skipped += 1
                    continue
                session.add(Listing(**{key: item[key] for key in (
                    'property_id', 'dataset_version', 'is_synthetic', 'deposit_toman',
                    'monthly_rent_toman', 'area_m2', 'bedrooms', 'parking', 'elevator')}, payload=item))
                inserted += 1
        return {'inserted': inserted, 'skipped_existing': skipped}
