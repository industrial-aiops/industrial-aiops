"""Investigation readiness — how far into an investigation this site could get.

HLD §13. The dry half of the investigation layer (D33): no incident, no device
contact, no analysis. It answers only the capability question, over the same
facts `readiness` gathers.
"""

from iaiops.core.investigate.assess import assess_investigation
from iaiops.core.investigate.model import InvestigationReadiness, Step

__all__ = ["assess_investigation", "InvestigationReadiness", "Step"]
