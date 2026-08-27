"""Assess how far into an investigation a site could get. Touches nothing.

Deliberately thin: it reuses `readiness.gather_facts` rather than re-reading the
config and store. Two assessments that disagree about the same site would be
worse than either of them alone, and the way that happens is two gatherers.

[READ] Config + local store only. No device, no network, no historian.
"""

from __future__ import annotations

from typing import Any

from iaiops.core.investigate.model import InvestigationReadiness
from iaiops.core.investigate.steps import build_steps


def assess_investigation(
    config: Any = None, db_path: Any = None, site: str = "default"
) -> InvestigationReadiness:
    """Eight steps judged against this site, and how far the walk gets."""
    from iaiops.core.knowledge.mechanisms import mounted_mechanisms
    from iaiops.core.knowledge.relations import line_relations
    from iaiops.core.readiness.assess import gather_facts

    facts = gather_facts(config=config, db_path=db_path)
    # Declared line order is a SITE fact, not a config or store one, so it is not
    # part of what `readiness` gathers. Counted here rather than fetched inside a
    # step builder, which must stay pure (they take facts, not the world).
    facts["declared_relations"] = len(line_relations(site=str(site or "default")))
    facts["mounted_mechanisms"] = len(mounted_mechanisms(site=str(site or "default")))
    return InvestigationReadiness(site=str(site or "default"), steps=build_steps(facts))
