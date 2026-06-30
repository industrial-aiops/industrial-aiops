"""IEC 61850 MMS client adapter over ``libiec61850`` (待核实, read-only).

libiec61850's Python binding (SWIG) exposes a procedural ``IedConnection`` API:
create → connect → browse the model (logical devices → logical nodes → data
objects/attributes) → read a data attribute by object-reference + functional
constraint (FC, e.g. MX for measurands, ST for status). The exact symbol names
vary by binding build and are **UNVERIFIED** here (preview), so all library calls
are isolated in this adapter behind a uniform interface
(``connect`` / ``close`` / ``get_logical_devices`` / ``get_data_directory`` /
``read``). The binding is imported LAZILY in :func:`build_mms_adapter`.
"""

from __future__ import annotations

from typing import Any

# IEC 61850 functional constraints we surface for reads (monitor-relevant subset).
FUNCTIONAL_CONSTRAINTS = ("MX", "ST", "CF", "DC", "SP", "SG", "SE", "EX")


def build_mms_adapter(host: str, port: int) -> Any:
    """Build an IEC 61850 MMS client adapter for ``host:port`` (待核实).

    The binding is the libiec61850 SWIG wrapper, published on PyPI as ``pyiec61850``
    (NOT the unrelated ``iec61850`` async-OOP distribution). Its procedural
    ``IedConnection_*`` symbol surface was verified present 2026-06-30; the live-IED
    read path remains 待核实.
    """
    import pyiec61850 as iec61850

    return _LibIec61850Adapter(iec61850, host, port)


class _LibIec61850Adapter:
    """Uniform read adapter over a libiec61850 ``IedConnection`` (待核实).

    Only browse + read are exposed (read-only). Control blocks (Oper/SBO) are not
    wired. Methods degrade gracefully — a binding that lacks a helper returns an
    empty list rather than raising.
    """

    def __init__(self, lib: Any, host: str, port: int) -> None:
        self._lib = lib
        self._host = host
        self._port = port
        self._conn = None

    def connect(self) -> None:
        lib = self._lib
        self._conn = lib.IedConnection_create()
        # IedConnection_connect(con, &error, host, port) — error is returned/out.
        result = lib.IedConnection_connect(self._conn, self._host, self._port)
        # Bindings vary: some return a tuple ``(error, …)``, some a bare error code
        # (IedClientError scalar). Treat a non-zero code in EITHER form as a failure
        # so a bad connect raises the teaching error instead of "succeeding" and
        # confusing later reads.
        code = result[0] if isinstance(result, tuple) and result else result
        if isinstance(code, int) and code not in (0,):
            raise ConnectionError(f"IedConnection_connect error={code}")

    def close(self) -> None:
        lib, con = self._lib, self._conn
        if con is None:
            return
        for name in ("IedConnection_close", "IedConnection_destroy"):
            fn = getattr(lib, name, None)
            if callable(fn):
                try:
                    fn(con)
                except Exception:  # noqa: BLE001 — teardown is best-effort
                    pass

    def get_logical_devices(self) -> list[str]:
        return self._to_str_list(self._call("IedConnection_getLogicalDeviceList"))

    def get_data_directory(self, reference: str) -> list[str]:
        """Browse children of a model reference (LD, LN, or DO)."""
        for name in ("IedConnection_getDataDirectory",
                     "IedConnection_getLogicalNodeDirectory",
                     "IedConnection_getLogicalDeviceDirectory"):
            fn = getattr(self._lib, name, None)
            if callable(fn):
                try:
                    return self._to_str_list(fn(self._conn, reference))
                except TypeError:
                    continue
        return []

    def read(self, reference: str, fc: str) -> dict:
        """Read one data attribute by object-reference + functional constraint."""
        lib = self._lib
        fc_val = self._fc_value(fc)
        reader = getattr(lib, "IedConnection_readObject", None)
        if not callable(reader):
            return {"reference": reference, "fc": fc, "error": "binding lacks readObject"}
        mms_value = reader(self._conn, reference, fc_val)
        if mms_value is None:
            return {"reference": reference, "fc": fc,
                    "error": "no value returned (object not found / read failed)"}
        value = self._decode_mms(mms_value)
        delete = getattr(lib, "MmsValue_delete", None)  # free the C MmsValue (avoid leak)
        if callable(delete):
            try:
                delete(mms_value)
            except Exception:  # noqa: BLE001 — free is best-effort
                pass
        return {"reference": reference, "fc": fc, "value": value}

    # ─── helpers (binding-tolerant) ──────────────────────────────────────────

    def _call(self, fn_name: str) -> Any:
        fn = getattr(self._lib, fn_name, None)
        if not callable(fn):
            return []
        try:
            return fn(self._conn)
        except Exception:  # noqa: BLE001 — absent/raised helper → empty
            return []

    def _fc_value(self, fc: str) -> Any:
        """Resolve a functional-constraint string to the binding's FC enum value."""
        fc = (fc or "MX").upper()
        getter = getattr(self._lib, "FunctionalConstraint_fromString", None)
        if callable(getter):
            try:
                return getter(fc)
            except Exception:  # noqa: BLE001
                pass
        return getattr(self._lib, f"IEC61850_FC_{fc}", fc)

    def _decode_mms(self, mms_value: Any) -> Any:
        """Best-effort decode of an MmsValue to a Python scalar/string (待核实)."""
        lib = self._lib
        for name, _ in (("MmsValue_toFloat", float), ("MmsValue_toInt32", int),
                        ("MmsValue_getBoolean", bool)):
            fn = getattr(lib, name, None)
            if callable(fn):
                try:
                    return fn(mms_value)
                except Exception:  # noqa: BLE001 — wrong type for this accessor
                    continue
        to_str = getattr(lib, "MmsValue_toString", None)
        if callable(to_str):
            try:
                return to_str(mms_value)
            except Exception:  # noqa: BLE001
                pass
        return str(mms_value)

    @staticmethod
    def _to_str_list(value: Any) -> list[str]:
        """Coerce a (possibly linked-list) binding result into a list of str."""
        if value in (None, ""):
            return []
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        try:
            return [str(v) for v in value]  # iterable LinkedList shim
        except TypeError:
            return [str(value)]


__all__ = ["build_mms_adapter", "FUNCTIONAL_CONSTRAINTS"]
