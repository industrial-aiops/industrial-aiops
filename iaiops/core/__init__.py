"""Shared core for Industrial-AIOps connectors.

Bundles the governance harness, the cross-protocol intelligence ("brain"), and
the runtime (sessions / config / encrypted secrets). Every protocol connector
imports from here; nothing protocol-specific lives in ``core``.
"""
