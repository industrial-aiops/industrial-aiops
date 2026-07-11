"""Shared OT tag semantics: class inference + alias canonicalization (pure).

This is the SINGLE home for the heuristic that turns a cryptic tag/browse name
into a semantic class (``temperature`` / ``pressure`` / ``alarm`` …) and the
scheme that canonicalizes an asset path + tag name into a clean dotted alias.

Both the OPC-UA discovery layer (:mod:`iaiops.connectors.opcua.discovery`, which
re-exports ``classify_tag`` / ``suggest_alias`` for API stability) and the
cross-protocol asset model (:mod:`iaiops.core.brain.asset_model`) import from
here so the SAME classes + alias rules apply everywhere — no divergent fork.

Pure, no I/O — fully unit-testable.
"""

from __future__ import annotations

# Semantic class → name substrings (checked lowercased, first match wins).
# Ordered so more-specific classes (setpoint, runtime) precede generic ones, and
# physical quantities precede the generic 'command' class (so "Startup_Temperature"
# classifies by its quantity, not the bare verb). 'command' MUST stay last.
#
# Substring hints are deliberately underscore/symbol-guarded where the bare token
# is ambiguous (e.g. ``_ph``/``ph_`` for pH, so "graph"/"phase" don't false-match;
# ``_ec_`` for conductivity), trading a little recall for far fewer wrong labels —
# the classifier prefers an honest ``other`` over a confident-but-wrong class.
_CLASS_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # ── renewables (solar PV / wind) — FIRST: specific classes that would otherwise be shadowed
    # by greedy generic hints (e.g. "_sp" of setpoint matches "_speed"). Hints are specific enough
    # not to false-match non-renewables tags. Grid/substation telecontrol lives in iaiops-energy.
    ("irradiance", ("irradiance", "irradiation", "_ghi", "ghi_", "_dni", "dni_",
                    "_poa", "poa_", "辐照", "w/m2", "w/m²", "wm2")),
    ("wind_speed", ("wind_speed", "windspeed", "风速", "_ws_")),
    ("rotor_speed", ("rotor_speed", "rotorspeed", "转子转速", "generator_speed", "rpm_rotor")),
    ("pitch_angle", ("pitch_angle", "blade_pitch", "桨距", "_pitch_", "pitch_deg")),
    ("yaw_angle", ("yaw_angle", "yaw_position", "偏航", "_yaw_", "nacelle_dir")),
    ("state_of_charge", ("state_of_charge", "stateofcharge", "_soc", "soc_", "荷电")),
    ("setpoint", ("setpoint", "_sp", "sptval", "target")),
    ("alarm", ("alarm", "alert", "fault", "trip", "fail")),
    ("state", ("state", "status", "running", "ready", "mode")),
    # ── water / process-treatment quantities (水处理; specific before generic) ──
    # Guarded like pH: bare "do"/"tmp"/"orp" are ambiguous (cool_down, temperature
    # abbreviations, torpedo…), so hints require underscore context or the full
    # word — honest 'other' beats a confident-but-wrong class.
    ("dissolved_oxygen",
     ("dissolved_oxygen", "dissolvedoxygen", "溶解氧", "do_", "_do_")),
    ("orp", ("_orp", "orp_", "oxidation_reduction", "redox", "氧化还原")),
    ("chlorine", ("chlorine", "余氯", "总氯", "hypochlor", "_cl2", "cl2_",
                  "free_cl", "total_cl")),
    ("ammonia", ("ammonia", "氨氮", "nh3", "_nh4", "nh4_")),
    ("suspended_solids", ("suspended_solids", "suspendedsolids", "悬浮物",
                          "_tss", "tss_", "mlss", "_ss_")),
    # Transmembrane pressure (跨膜压差, membrane filtration). Bare "tmp" is a
    # common PLC abbreviation for temperature, so it is only matched alongside
    # membrane context — must precede the generic 'pressure' class.
    ("membrane_pressure", ("跨膜压差", "transmembrane", "trans_membrane",
                           "membrane_press", "membranepress", "tmp_membrane",
                           "membrane_tmp")),
    ("uv_intensity", ("uv_intensity", "uvintensity", "uv_dose", "_uvi", "uvi_",
                      "紫外")),
    # water-plant equipment (dosing/加药 metering pumps, aeration blowers/曝气风机)
    ("dosing", ("dosing", "加药", "metering_pump")),
    ("aeration", ("aeration", "曝气", "blower", "风机")),
    # ── physical quantities (specific units help disambiguate) ──
    ("temperature",
     ("temp", "temperature", "_t_", "degc", "degf", "°c", "°f", "celsius", "fahrenheit")),
    ("humidity", ("humidity", "humid", "_rh", "rh_", "rh%", "%rh", "dewpoint", "dew_point")),
    ("pressure", ("press", "pressure", "_p_", "bar", "psi", "kpa", "mbar", "mmhg", "torr")),
    ("flow", ("flow", "_fl_", "lpm", "gpm", "m3h", "m³/h", "m3/h", "scfm", "cfm", "nm3",
              "流量")),
    ("level", ("level", "_lv_", "tanklvl", "ullage", "液位")),
    # no bare "conduct" — it false-matches Conductor*; "conductivity" already covers it.
    ("conductivity", ("conductivity", "_ec_", "_ec", "us/cm", "µs/cm", "ms/cm")),
    ("ph", ("_ph", "ph_", "phval", "ph_value", "potential_hydrogen")),
    # "_ntu" (not bare "ntu") so it doesn't match incidental words (e.g. Adventure).
    ("turbidity", ("turbidity", "turbid", "_ntu", "ntu_", "_fnu", "nephelo")),
    ("density", ("density", "densit", "kg/m3", "g/cm3", "g/ml", "specificgravity",
                 "specific_gravity")),
    # frequency (VFD/line Hz) is split OUT of speed so a drive's output frequency
    # and a motor's RPM are distinct quantities (frequency-vs-speed disambiguation).
    ("frequency", ("frequency", "freq", "hz", "hertz")),
    ("speed", ("speed", "rpm", "velocity", "_spd")),
    ("torque", ("torque",)),
    ("power", ("power", "_kw", "watt", "_pwr", "kvar", "kva")),
    ("energy", ("energy", "kwh", "consumption")),
    ("current", ("current", "amp", "_i_")),
    ("voltage", ("voltage", "volt", "_v_")),
    ("vibration", ("vibration", "vib", "accel")),
    # no bare "gram" — it false-matches Program/Histogram/Telegram (common PLC tags);
    # mass is covered by weight/mass/_kg/kg_/tonne/loadcell well enough.
    ("mass", ("weight", "mass", "_kg", "kg_", "tonne", "loadcell", "load_cell")),
    # valve position / opening are an analog feedback → the position class.
    ("position", ("position", "_pos", "encoder", "valve", "_vlv", "opening")),
    ("counter", ("count", "counter", "total", "qty")),
    ("runtime", ("runtime", "hours", "uptime", "elapsed")),
    ("command", ("command", "cmd", "start", "stop", "enable")),
)


def classify_tag(browse_name: str) -> str:
    """Infer a semantic class for a tag from its name (heuristic).

    Returns ``other`` when nothing matches rather than guessing — honest over a
    confident-but-wrong label that downstream tooling would trust.
    """
    text = str(browse_name or "").lower()
    for klass, hints in _CLASS_HINTS:
        if any(h in text for h in hints):
            return klass
    return "other"


def alias_segment(text: str) -> str:
    """Lowercase a path/name segment to an alias-safe token (alnum/_)."""
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in str(text).lower())
    return out.strip("_") or "unknown"


def suggest_alias(asset_path: str, browse_name: str) -> str:
    """Propose a clean canonical alias ``<asset>.<tag>`` (dot-delimited, advisory)."""
    parts = [alias_segment(p) for p in str(asset_path or "").split("/") if p]
    tag = alias_segment(browse_name)
    return ".".join([*parts, tag]) if parts else tag


__all__ = ["classify_tag", "alias_segment", "suggest_alias"]
