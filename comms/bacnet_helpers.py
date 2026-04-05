"""
HBCE — Hybrid Controls Editor
comms/bacnet_helpers.py — Shared BAC0 / bacpypes3 helper functions

Internal module — imported by bacnet_ip.py and bacnet_mstp.py only.
Not part of the public adapter API.

Handles the two areas where BAC0≥22.9 (bacpypes3 backend) returns
complex typed objects that need conversion to plain Python values:

  _bacnet_ts_to_str(ts)      — BACnet DateTime → ISO-8601 string
  _logdatum_to_float(datum)  — LogRecord datum choice → float or None
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def _bacnet_ts_to_str(ts) -> str:
    """
    Convert a BAC0 / bacpypes3 DateTime to an ISO-8601 string.

    Handles three possible shapes:
      1. Python datetime — has .isoformat()
      2. bacpypes3 DateTime — has .date.year / .time.hour etc.
      3. Anything else — str() fallback
    """
    if ts is None:
        return datetime.now().isoformat(timespec="seconds")

    # Shape 1: Python datetime or date/time
    if hasattr(ts, "isoformat"):
        return ts.isoformat(timespec="seconds")

    # Shape 2: bacpypes3 DateTime composite
    try:
        d = ts.date
        t = ts.time
        year   = int(d.year)   if hasattr(d, "year")   else 2000
        month  = int(d.month)  if hasattr(d, "month")  else 1
        day    = int(d.day)    if hasattr(d, "day")     else 1
        hour   = int(t.hour)   if hasattr(t, "hour")   else 0
        minute = int(t.minute) if hasattr(t, "minute") else 0
        second = int(t.second) if hasattr(t, "second") else 0
        # BACnet unspecified year == 255
        if year == 255:
            year = 2000
        return datetime(year, month, day, hour, minute, second).isoformat(
            timespec="seconds"
        )
    except Exception:
        pass

    return str(ts)


def _logdatum_to_float(datum) -> Optional[float]:
    """
    Extract a numeric value from a bacpypes3 LogRecord datum choice.

    BACnet LogRecord.logDatum is a CHOICE with these relevant alternatives:
      realValue      — most common for analogs
      unsignedValue  — unsigned integer objects
      integerValue   — signed integer objects
      enumValue      — multi-state / enum objects
      booleanValue   — binary objects
      nullValue      — present when the object has no valid reading
      failure        — read error logged by the controller
      timeChange     — clock-change marker, not a data record

    Returns None for null / failure / timeChange so callers can skip them.
    """
    if datum is None:
        return None

    # Data-bearing alternatives — try in priority order
    for attr in ("realValue", "unsignedValue", "integerValue",
                 "enumValue", "booleanValue"):
        val = getattr(datum, attr, None)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None

    # Non-data alternatives — return None so callers skip the entry
    # (nullValue, failure, timeChange)
    return None
