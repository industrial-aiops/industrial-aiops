"""The sensor profile library (HLD §17.3) — data files, one per device family.

Each ``<category>/<id>.yaml`` is an ordinary sensor profile. Entries are
``verified: 待核实`` unless they carry ``provenance`` evidence; vendor names
appear only inside these files (brand isolation, HLD §16.3). Query with
``iaiops sensor list | show`` or the ``sensor_profile_list`` / ``_show`` tools.
"""
