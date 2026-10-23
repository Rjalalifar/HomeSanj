"""Additive evaluation metadata; canonical search and annotation rows are reused."""
from sqlalchemy import JSON, Float, Integer, String, inspect, text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, Migration, utcnow


class ReplayManifest(Base):
    __tablename__ = 'evaluation_manifests'
    manifest_id: Mapped[str] = mapped_column(String, primary_key=True)
    request_id: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String)


class DatasetVersion(Base):
    __tablename__ = 'annotation_datasets'
    dataset_id: Mapped[str] = mapped_column(String, primary_key=True)
    manifest: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String)


class OfflineJob(Base):
    __tablename__ = 'offline_jobs'
    job_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, index=True, default='queued')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String)


class Experiment(Base):
    __tablename__ = 'evaluation_experiments'
    experiment_id: Mapped[str] = mapped_column(String, primary_key=True)
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String)


class Release(Base):
    __tablename__ = 'evaluation_releases'
    release_id: Mapped[str] = mapped_column(String, primary_key=True)
    scope: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSON)
    previous_id: Mapped[str | None] = mapped_column(String, nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)


def migrate_evaluation(db):
    with db.engine.begin() as connection:
        for table, column in [('review_samples', 'workflow'), ('review_annotations', 'annotation_data')]:
            if column not in {v['name'] for v in inspect(connection).get_columns(table)}:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} JSON NOT NULL DEFAULT '{{}}'"))
    with db.session.begin() as session:
        if not session.get(Migration, 4):
            session.add(Migration(version=4, applied_at=utcnow()))
