"""Legacy PLC program explainer (A8) — structural extraction over EXPORTED files.

Analyzes exported program text (Siemens SCL/ST, AWL/STL, Rockwell L5X) — never
a live PLC upload. The LLM agent does the explaining; these functions extract
structure with mandatory source citations (file + line / rung number) so the
agent can't hallucinate locations. Advisory, regex/line/xml based — honest
about what is extracted vs skipped (see each parser's docstring).
"""

from iaiops.core.brain.plc_program.model import (
    Block,
    Branch,
    CallEdge,
    ProgramOutline,
    TimerCounter,
    Variable,
    XrefHit,
)
from iaiops.core.brain.plc_program.outline import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_BYTES,
    block_section,
    load_program,
    outline_program,
    outline_stats,
    outline_to_bounded_dict,
    sniff_format,
    validate_program_path,
)
from iaiops.core.brain.plc_program.xref import find_symbol

__all__ = [
    "ALLOWED_EXTENSIONS",
    "MAX_FILE_BYTES",
    "Block",
    "Branch",
    "CallEdge",
    "ProgramOutline",
    "TimerCounter",
    "Variable",
    "XrefHit",
    "block_section",
    "find_symbol",
    "load_program",
    "outline_program",
    "outline_stats",
    "outline_to_bounded_dict",
    "sniff_format",
    "validate_program_path",
]
