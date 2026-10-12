"""A minimal reference Chronicle control plane.

A shared HTTP service that deployed agents ship envelopes to via ``RemoteStore``, backed
by SQLite. Zero dependency (stdlib ``http.server`` + ``sqlite3``). TokenOps can point at
the same service to co-locate cost ledger and trace storage. See ``server.py``.
"""
