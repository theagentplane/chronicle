"""The control-plane endpoints Chronicle calls, in one place (design sections 5.1, 5.2 and 10.2).

The exact endpoint list is not final. Only this module and ``HttpControlPlaneClient`` know the
paths, so if the control plane changes them only the client changes.
"""

TRACES = "/v1/traces"
"""``POST``: register a trace (idempotent: client-supplied id, labels written once)."""

ENVELOPES_BATCH = "/v1/envelopes:batch"
"""``POST``: append envelopes. Body ``{"envelopes": [...]}``. Exists in control-plane 0.2.x."""


def span_path(trace_id: str, span_id: str) -> str:
    """``PUT``: create or update a span."""
    return f"/v1/traces/{trace_id}/spans/{span_id}"


def span_envelopes_path(trace_id: str, span_id: str) -> str:
    """``GET``: the envelopes of one span in one trace, for replay."""
    return f"/v1/traces/{trace_id}/spans/{span_id}/envelopes"
