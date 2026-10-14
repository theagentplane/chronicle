"""The wire shapes Chronicle reads back from the control plane (primitives ADR 0003).

The HTTP request and response wrappers belong to the control plane, not to primitives. Chronicle
imports primitives for the entities (the request bodies) and reads the write result and error
body itself. These models are deliberately tolerant: unknown fields are ignored and every field
is optional, so a control-plane release that adds a field does not break the SDK. The contract
test in ``tests/test_wire_contract.py`` pins what Chronicle relies on.
"""

from pydantic import BaseModel, ConfigDict


class WriteResult(BaseModel):
    """What a write returns, for example ``{"status": "stored", "accepted": 3, "deduped": 0}``."""

    model_config = ConfigDict(extra="ignore")

    status: str | None = None
    accepted: int | None = None
    deduped: int | None = None


class ErrorBody(BaseModel):
    """An error response, for example FastAPI's ``{"detail": "..."}``."""

    model_config = ConfigDict(extra="ignore")

    detail: str | list[object] | None = None
    error: str | None = None
    message: str | None = None
