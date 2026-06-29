"""Protocol connectors. Each subpackage is self-contained and imports the shared
``iaiops.core`` (governance + runtime + brain). Protocol client libraries are
optional extras, imported lazily so the base package installs without them.
"""
