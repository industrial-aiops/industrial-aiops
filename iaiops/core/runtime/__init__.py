"""Runtime: OT connection sessions, YAML config loading, encrypted secret store.

Re-exports the generic session factory so downstream packages (e.g.
``iaiops-energy``) can assemble their own protocol sessions with the same
guard/translate/teardown lifecycle::

    from iaiops.core.runtime import OTConnectionError, make_session
"""

from iaiops.core.runtime.session_factory import OTConnectionError, make_session

__all__ = ["OTConnectionError", "make_session"]
