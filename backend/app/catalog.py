"""Versioned public inventory, geometry assignments, and a SQLite lexical baseline."""
from __future__ import annotations

import hashlib
import json
import re
import threading

from sqlalchemy import JSON, Float, Index, String, delete, select, text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, Listing, Migration, utcnow
from .normalize import normalize_text

ASSIGNMENTS_VERSION = 'covers-original-geometry-2'
KEYWORD_POLICY = 'normalized-token-and-v1'


class ListingAssignment(Base):
    __tablename__ = 'listing_assignments'
    property_id: Mapped[str] = mapped_column(String, primary_key=True)
    boundary_version: Mapped[str] = mapped_column(String, index=True)
    listing_hash: Mapped[str] = mapped_column(String)
    neighborhood_ids: Mapped[list] = mapped_column(JSON)
    district_ids: Mapped[list] = mapped_column(JSON)
    search_text: Mapped[str] = mapped_column(String)
    updated_at: Mapped[str] = mapped_column(String)


class LocationMember(Base):
    __tablename__ = 'listing_location_members'
    property_id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, primary_key=True)
    area_id: Mapped[str] = mapped_column(String, primary_key=True)
    __table_args__ = (Index('ix_location_lookup', 'kind', 'area_id', 'property_id'),)


class SearchAnalysis(Base):
    __tablename__ = 'search_analyses'
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    search_mode: Mapped[str] = mapped_column(String, default='normal')
    status: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    priority_ids: Mapped[list] = mapped_column(JSON, default=list)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def feature_id(f):
    p = f.get('properties', {})
    return str(f.get('id') or p.get('id') or p.get('neighborhood_id') or p.get('district_id') or p.get('area_id'))


def tokens(value):
    return re.findall(r'[\w]+', normalize_text(value), flags=re.UNICODE)[:30]


def keyword_match(query, searchable):
    words = tokens(searchable)
    return all(any(word.startswith(token) for word in words) for token in tokens(query))


def migrate_catalog(db):
    Base.metadata.create_all(db.engine)
    with db.engine.begin() as connection:
        connection.execute(text('CREATE TABLE IF NOT EXISTS inventory_revision (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL)'))
        connection.execute(text('INSERT OR IGNORE INTO inventory_revision(id,revision) VALUES(1,0)'))
        for action in ('INSERT', 'UPDATE', 'DELETE'):
            connection.execute(text(f'CREATE TRIGGER IF NOT EXISTS inventory_changed_{action.lower()} AFTER {action} ON listings BEGIN UPDATE inventory_revision SET revision=revision+1 WHERE id=1; END'))
        for name, columns in [
            ('ix_listing_price_order', 'dataset_version, monthly_rent_toman, deposit_toman, property_id'),
            ('ix_listing_deposit_order', 'dataset_version, deposit_toman, monthly_rent_toman, property_id'),
            ('ix_listing_attributes', 'dataset_version, bedrooms, area_m2, parking, elevator'),
        ]:
            connection.execute(text(f'CREATE INDEX IF NOT EXISTS {name} ON listings ({columns})'))
        try:
            connection.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS listing_fts USING fts5(property_id UNINDEXED, body, tokenize='unicode61 remove_diacritics 0')"))
            fts = True
        except Exception:
            fts = False
    with db.session.begin() as session:
        if not session.get(Migration, 2):
            session.add(Migration(version=2, applied_at=utcnow()))
    return fts


class Catalog:
    def __init__(self, db, geo):
        self.db, self.geo = db, geo
        self.fts = migrate_catalog(db)
        self.lock = threading.Lock()
        self.version = None
        self.revision = None
        self.public = None
        self.boundary_version = digest({'version': ASSIGNMENTS_VERSION,
                                       'neighborhoods': geo.neighborhoods, 'districts': geo.districts})
        self.names = {feature_id(f): f.get('properties', {}).get('name_fa', '') for f in geo.neighborhoods}

    def refresh(self):
        with self.lock:
            with self.db.engine.connect() as connection:
                revision = connection.scalar(text('SELECT revision FROM inventory_revision WHERE id=1'))
            if self.revision == revision and self.public is not None:
                return
            with self.db.session() as session:
                rows = list(session.scalars(select(Listing).where(
                    Listing.dataset_version == self.geo.dataset_version).order_by(Listing.property_id)))
                signature = digest({'listings': [(row.property_id, row.payload) for row in rows], 'boundary_version': self.boundary_version})
                if signature == self.version:
                    return
                existing = {a.property_id: a for a in session.scalars(select(ListingAssignment))}
            active = {row.property_id for row in rows}
            updates = []
            public = []
            for row in rows:
                item = row.payload
                item_hash = digest(item)
                assignment = existing.get(row.property_id)
                if assignment is None or assignment.listing_hash != item_hash or assignment.boundary_version != self.boundary_version:
                    lon, lat = item.get('longitude'), item.get('latitude')
                    located = lon is not None and lat is not None
                    ns = self.geo.neighborhood_memberships(lon, lat) if located else []
                    ds = self.geo.district_memberships(lon, lat) if located else []
                    searchable = normalize_text(' '.join([
                        item.get('title_fa', ''), *[self.names.get(n, '') for n in ns],
                        'پارکینگ' if item.get('parking') is True else '',
                        'آسانسور' if item.get('elevator') is True else '',
                        f"{item['bedrooms']} اتاق" if item.get('bedrooms') is not None else '',
                    ]))
                    assignment = ListingAssignment(property_id=row.property_id, boundary_version=self.boundary_version,
                        listing_hash=item_hash, neighborhood_ids=ns, district_ids=ds,
                        search_text=searchable, updated_at=utcnow())
                    updates.append(assignment)
                if row.is_synthetic:
                    safe = {key: value for key, value in item.items() if key != 'source_records'}
                    safe['source_records'] = [{key: record.get(key) for key in ('source', 'source_id', 'published_at', 'collected_at')}
                                              for record in item.get('source_records', [])]
                    safe.update(neighborhood_ids=assignment.neighborhood_ids,
                                district_ids=assignment.district_ids,
                                neighborhood_names=[self.names.get(n, '') for n in assignment.neighborhood_ids],
                                search_text=assignment.search_text)
                    safe['neighborhood_membership_status'] = self.membership_status(safe, assignment.neighborhood_ids)
                    safe['district_membership_status'] = self.membership_status(safe, assignment.district_ids)
                    public.append(safe)
            with self.db.session.begin() as session:
                stale = set(existing) - active
                for pid in stale:
                    session.execute(delete(ListingAssignment).where(ListingAssignment.property_id == pid))
                    session.execute(delete(LocationMember).where(LocationMember.property_id == pid))
                    if self.fts:
                        session.execute(text('DELETE FROM listing_fts WHERE property_id=:pid'), {'pid': pid})
                for assignment in updates:
                    session.merge(assignment)
                    session.execute(delete(LocationMember).where(LocationMember.property_id == assignment.property_id))
                    for kind, ids in [('neighborhood', assignment.neighborhood_ids), ('district', assignment.district_ids)]:
                        for aid in ids:
                            session.add(LocationMember(property_id=assignment.property_id, kind=kind, area_id=aid))
                    if self.fts:
                        session.execute(text('DELETE FROM listing_fts WHERE property_id=:pid'), {'pid': assignment.property_id})
                        session.execute(text('INSERT INTO listing_fts(property_id,body) VALUES (:pid,:body)'),
                                        {'pid': assignment.property_id, 'body': assignment.search_text})
            self.version = signature
            self.revision = revision
            self.public = {'dataset_version': self.geo.dataset_version, 'inventory_version': signature,
                           'boundary_version': self.boundary_version, 'assignments_version': ASSIGNMENTS_VERSION,
                           'properties': public, 'count': len(public), 'scope': 'public_demo',
                           'keyword_policy': KEYWORD_POLICY, 'fts5_available': self.fts,
                           'boundary_policy': 'covers; boundary included; multiple memberships ambiguous'}

    @staticmethod
    def membership_status(item, ids):
        if item.get('longitude') is None:
            return 'unknown'
        return 'ambiguous' if len(ids) > 1 else 'unique' if ids else 'outside'

    def lexical(self, query, limit=200, any_token=False):
        words = tokens(query)
        if not words:
            return []
        with self.db.session() as session:
            if self.fts:
                # Only normalized word tokens enter MATCH; operators come from this code.
                expression = (' OR ' if any_token else ' AND ').join('"' + word + '"*' for word in words)
                return list(session.execute(text(
                    'SELECT property_id FROM listing_fts WHERE listing_fts MATCH :query ORDER BY bm25(listing_fts),property_id LIMIT :limit'
                ), {'query': expression, 'limit': limit}).scalars())
            return [row.property_id for row in session.scalars(select(ListingAssignment).order_by(ListingAssignment.property_id))
                    if (any(keyword_match(word, row.search_text) for word in words) if any_token else keyword_match(query, row.search_text))][:limit]
