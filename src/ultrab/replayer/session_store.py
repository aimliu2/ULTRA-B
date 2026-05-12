from __future__ import annotations

from ultrab.replayer.replay_session import ReplaySession


_SESSIONS: dict[str, ReplaySession] = {}


def save_session(session: ReplaySession) -> ReplaySession:
    _SESSIONS[session.session_id] = session
    return session


def get_session(session_id: str) -> ReplaySession:
    return _SESSIONS[session_id]

