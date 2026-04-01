"""Public models for Browser Session Hub."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    """Browser session lifecycle state."""

    starting = "starting"
    running = "running"
    stopped = "stopped"
    error = "error"


class CreateSessionRequest(BaseModel):
    """API payload used to create a browser session."""

    owner_id: str = Field(default="anonymous", min_length=1, max_length=128)
    start_url: str | None = Field(default=None, max_length=4096)
    viewport_width: int | None = Field(default=None, ge=320, le=3840)
    viewport_height: int | None = Field(default=None, ge=240, le=2160)
    persist_profile: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)


class DependencyStatus(BaseModel):
    """Runtime dependency report."""

    name: str
    path: str | None
    available: bool
    required: bool = True
    note: str | None = None


class SessionSummary(BaseModel):
    """Serializable browser session state."""

    session_id: str
    owner_id: str
    status: SessionStatus
    created_at: float
    last_activity: float
    start_url: str
    persist_profile: bool
    working_dir: str
    profile_dir: str
    cdp_http_endpoint: str
    cdp_ws_endpoint: str | None = None
    preview_url: str
    display_number: int
    cdp_port: int
    vnc_port: int
    novnc_port: int
    viewport_width: int
    viewport_height: int
    processes: dict[str, int | None]
    metadata: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class SessionListResponse(BaseModel):
    """List response for session summaries."""

    sessions: list[SessionSummary]


class HealthResponse(BaseModel):
    """Basic service health payload."""

    ok: bool
    service: str
    version: str


class CreateSessionResponse(BaseModel):
    """Create session response payload."""

    session: SessionSummary


class ErrorResponse(BaseModel):
    """Simple error response."""

    detail: str
    context: dict[str, Any] = Field(default_factory=dict)
