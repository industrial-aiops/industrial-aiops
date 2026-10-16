"""Write the synthetic half-hourly file the metering demo reads.

Deterministic (fixed seed), so the committed CSV is reproducible:

    python demo/metering/generate_sample.py > demo/metering/college_hh_sample.csv

**Synthetic — not any real site.** It is shaped like a small further-education
college so the report has something to find:

* term-time weekdays ~60 kW 08:00–17:30, overnight base ~18 kW
* heating/ventilation left running until 21:00 Monday–Thursday (the "finding")
* Saturday-morning sports hall use; quiet Sundays; a lighter half-term week
* the clock-change day 25 Oct 2026 has 50 half hours (wide file, 50 columns)
* 3 Nov 2026 10:00–16:00 is missing (blank cells) — a data-collector gap
* 14–16 Sep 2026 are flagged E (estimated) in the Read Type column
"""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from iaiops.core.brain import uk_clock  # noqa: E402

MPAN = "1099999999990"  # synthetic: not a real supply number
FIRST, LAST = date(2026, 9, 1), date(2026, 11, 30)
HALF_TERM = (date(2026, 10, 26), date(2026, 10, 30))
GAP_DAY, GAP_SLOTS = date(2026, 11, 3), range(20, 32)
ESTIMATED_DAYS = {date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)}


def _kw(day: date, minute: int, rng: random.Random) -> float:
    base = 18.0
    weekday = day.weekday()
    term = not (HALF_TERM[0] <= day <= HALF_TERM[1])
    if weekday < 5 and 8 * 60 <= minute < 17 * 60 + 30:
        kw = 60.0 if term else 30.0
    elif weekday < 4 and 17 * 60 + 30 <= minute < 21 * 60:
        kw = 35.0  # HVAC overrun after the building empties
    elif weekday == 5 and 9 * 60 <= minute < 13 * 60:
        kw = 40.0
    else:
        kw = base
    return max(0.0, kw * (1 + rng.uniform(-0.08, 0.08)))


def rows() -> list[str]:
    rng = random.Random(42)  # noqa: S311 — synthetic demo data, not security
    head = ["MPAN", "Date", "Read Type", *(f"HH{i:02d}" for i in range(1, 51))]
    out = [",".join(head)]
    day = FIRST
    while day <= LAST:
        n = uk_clock.periods_in_day(day)
        midnight = uk_clock.local_midnight_utc(day)
        cells = []
        for i in range(50):
            if i >= n or (day == GAP_DAY and i in GAP_SLOTS):
                cells.append("")
                continue
            local = uk_clock.to_local(midnight + timedelta(minutes=30 * i))
            cells.append(f"{_kw(day, local.hour * 60 + local.minute, rng) / 2:.2f}")
        flag = "E" if day in ESTIMATED_DAYS else "A"
        out.append(",".join([MPAN, day.strftime("%d/%m/%Y"), flag, *cells]))
        day += timedelta(days=1)
    return out


if __name__ == "__main__":
    sys.stdout.write("\n".join(rows()) + "\n")
