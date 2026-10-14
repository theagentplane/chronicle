"""The closed sets used by the configuration (design section 2.9, config enums).

They are defined next to the code that acts on them; this module is the one place a developer
imports them from.
"""

from chronicle.capabilities.record.registration_enums import TraceRegistration
from chronicle.repositories.delivery_enums import OverflowPolicy

__all__ = ["OverflowPolicy", "TraceRegistration"]
