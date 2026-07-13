"""BAS controller-layer connector — vendor supervisory-controller REST above BACnet.

Speaks the *vendor supervisory controller* HTTP APIs that sit ABOVE the field
protocol (BACnet). This is deliberately NOT a second BACnet connector: BACnet
speaks the field bus (Who-Is, present-value at the device), whereas these
controllers expose an enterprise REST surface aggregating many field points,
alarms and trends behind one authenticated endpoint. Two dialects are covered
(resource paths + per-vendor field aliases live in :mod:`dialects`); the tools
are edition-scoped (building edition) and read-first, with ONE MOC-gated command.
Vendor names stay INSIDE this connector package (brand-isolation iron rule).
"""
