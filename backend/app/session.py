"""Opaque browser sessions and server-owned search authorization."""
from __future__ import annotations

import hashlib
import secrets
import time

from fastapi import HTTPException
from sqlalchemy import Float, String, select
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, SearchRequest


class BrowserSession(Base):
    __tablename__ = 'browser_sessions'
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    expires_at: Mapped[float] = mapped_column(Float)


class SearchOwner(Base):
    __tablename__ = 'search_owners'
    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(String, index=True)


def assert_owned(db, request_id, session_id):
    with db.session() as session:
        owner = session.get(SearchOwner, request_id)
        if owner is None or owner.session_id != session_id:
            raise HTTPException(404, 'Search is unavailable in this browser session')


def claim_request(db, request_id, session_id):
    with db.session.begin() as session:
        session.add(SearchOwner(request_id=request_id, session_id=session_id))


def assert_task_owned(db, task_id, session_id):
    with db.session() as session:
        found = session.scalar(select(SearchOwner.request_id).join(
            SearchRequest, SearchRequest.request_id == SearchOwner.request_id
        ).where(SearchRequest.task_id == task_id, SearchOwner.session_id == session_id).limit(1))
    if found is None:
        raise HTTPException(404, 'Task is unavailable in this browser session')


def install_sessions(app, db):
    @app.middleware('http')
    async def browser_session(request, call_next):
        if not request.url.path.startswith('/api/'):
            return await call_next(request)
        # Same-origin unsafe requests protect the local service from browser CSRF.
        origin = request.headers.get('origin')
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc != request.headers.get('host'):
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail': 'Cross-origin writes are not allowed'}, status_code=403)
        token = request.cookies.get('homesanj_session', '')
        identity = hashlib.sha256(token.encode()).hexdigest()
        with db.session() as session:
            saved = session.get(BrowserSession, identity)
            valid = saved is not None and saved.expires_at > time.time()
        if not valid:
            token = secrets.token_urlsafe(32)
            identity = hashlib.sha256(token.encode()).hexdigest()
            with db.session.begin() as session:
                session.add(BrowserSession(token_hash=identity, expires_at=time.time() + 86400 * 30))
        request.state.session_id = identity
        response = await call_next(request)
        if not valid:
            response.set_cookie('homesanj_session', token, httponly=True, samesite='strict',
                                secure=request.url.scheme == 'https', max_age=86400 * 30)
        return response
