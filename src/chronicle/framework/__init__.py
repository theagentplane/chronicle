"""The framework layer: in-process machinery with no network (design section 1.1, section 4).

Contents: the crossing interceptor, the kind registry, adapters, hooks, redaction, and the
context and recording session. Nothing here talks to the control plane; the session hands
finished records to an ``EnvelopeSink`` that the repositories layer implements.
"""
