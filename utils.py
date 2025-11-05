import requests
import json
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo  # Python 3.9+

    _HAS_ZONEINFO = True
except Exception:  # pragma: no cover - fallback path
    ZoneInfo = None  # type: ignore
    _HAS_ZONEINFO = False

try:
    import pytz  # Fallback if zoneinfo is unavailable

    _HAS_PYTZ = True
except Exception:  # pragma: no cover - optional dependency
    pytz = None  # type: ignore
    _HAS_PYTZ = False
from model_helpers import (
    create_port,
    initialize_db,
    create_vessel,
    update_port_logs,
    PortLog,
    PortLogNotification,
)


def _to_datetime(ts):
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts
    try:
        # Try ISO-style parsing first
        return datetime.fromisoformat(str(ts))
    except Exception:
        # Give up and return None — callers will handle None
        return None


def _seconds_between(new_ts, old_ts):
    """Return seconds between two timestamps or None on failure.

    Handles datetime objects and ISO-like strings. If tz-awareness mismatches
    (naive vs aware) we fallback to comparing naive times by dropping tzinfo.
    """
    n = _to_datetime(new_ts)
    o = _to_datetime(old_ts)
    if not n or not o:
        return None
    try:
        return (n - o).total_seconds()
    except TypeError:
        # likely naive vs aware mismatch — try comparing naive datetimes
        try:
            return (n.replace(tzinfo=None) - o.replace(tzinfo=None)).total_seconds()
        except Exception:
            return None
    except Exception:
        return None


def _format_duration(seconds: float | None) -> str | None:
    """Format seconds into 'HhMm' or 'Mm' without seconds (floor to minutes)."""
    if seconds is None:
        return None
    try:
        minutes = int(seconds) // 60
    except Exception:
        return None
    hours = minutes // 60
    mins = minutes % 60
    days = hours // 24
    hours = hours % 24

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if mins > 0:
        parts.append(f"{mins}m")

    # If all units are zero (duration < 60s), show '0m'
    if not parts:
        return "0m"

    return " ".join(parts)


# Maldives time zone (IANA): 'Indian/Maldives' (UTC+05:00)
_MALDIVES_TZNAME = "Indian/Maldives"


def _get_maldives_tz():
    """Return a tzinfo for Maldives, with graceful fallbacks.

    Order of preference:
      1) zoneinfo.ZoneInfo('Indian/Maldives') if available
      2) pytz.timezone('Indian/Maldives') if available
      3) Fixed-offset timezone UTC+05:00 as a last-resort
    """
    if _HAS_ZONEINFO:
        try:
            return ZoneInfo(_MALDIVES_TZNAME)
        except Exception:
            pass
    if _HAS_PYTZ:
        try:
            return pytz.timezone(_MALDIVES_TZNAME)
        except Exception:
            pass
    # Final fallback: fixed offset of +05:00
    return timezone(timedelta(hours=5))


def utc_to_maldives_time(ts, fmt: str | None = None) -> datetime | str | None:
    """Convert a UTC timestamp to Maldives local time (UTC+05:00).

    - Accepts datetime, ISO-like string (e.g. '2025-11-05T12:34:00Z' or '+00:00'), or epoch seconds.
    - If input is naive (no tzinfo), it's assumed to be UTC.
    - If `fmt` is provided, returns a formatted string via strftime; otherwise returns
      an aware datetime localized to 'Indian/Maldives'.

    Returns None if conversion fails.
    """
    if ts is None:
        return None

    dt: datetime | None = None
    # Fast-path for datetime
    if isinstance(ts, datetime):
        dt = ts
    # Epoch seconds
    elif isinstance(ts, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except Exception:
            return None
    # Strings (ISO-ish)
    elif isinstance(ts, str):
        s = ts.strip()
        # Handle trailing 'Z' designator
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            # Fall back to the module's tolerant parser
            dt = _to_datetime(s)
            if dt is None:
                return None
    else:
        # Last resort: try the tolerant helper
        dt = _to_datetime(ts)
        if dt is None:
            return None

    # Ensure timestamp is in UTC for correct conversion
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    except Exception:
        # If anything goes wrong, assume UTC
        dt = dt.replace(tzinfo=timezone.utc)

    local_dt = dt.astimezone(_get_maldives_tz())
    if fmt:
        try:
            return local_dt.strftime(fmt)
        except Exception:
            return None
    return local_dt


def api_request(api_key):
    url = f"https://followme.mv/api/v4/public/{api_key}"
    api_req = requests.get(url).text

    # converts api data to python dictionary
    all_vessels_dict = json.loads(
        BeautifulSoup(api_req, features="html.parser").find("body").get_text()
    )

    return all_vessels_dict["data"]


def update_port_info(api_data):
    for vessel in api_data:
        name = api_data[vessel]["port"]
        if name == "":
            continue
        else:
            create_port(name)


def update_vessel_info(api_data):
    for vessel in api_data:
        name = api_data[vessel]["name"]
        vessel_type = api_data[vessel]["type"]
        create_vessel(vessel, name, vessel_type)


def all_notify() -> dict:
    """
    Inspect the last 50 PortLog entries across all ports and return a dict
    of un-notified logs with vessel info.

    Returns a dict with 'arrivals' and 'departures' keys. Each value is a dict
    keyed by PortLog.id with the same structure as notify():
      - portlog_id, vessel_id, name, vessel_type, contact, last_port_name,
        event, timestamp, transit_time

    For arrivals, also includes:
      - departed: the time the vessel left its previous port (if known)

    For departures, also includes:
      - stay_time: how long the vessel stayed at this port
    """

    arrivals: dict = {}
    departures: dict = {}

    # Get last 50 un-notified logs across all ports
    query = (
        PortLog.select()
        .where(PortLog.notified == False)  # noqa: E712
        .order_by(PortLog.timestamp.desc())
        .limit(50)
    )

    for log in query:
        if not log.notified:
            vessel = log.vessel

            # Find previous log for this vessel
            prev_log = (
                PortLog.select()
                .where((PortLog.vessel == vessel) & (PortLog.timestamp < log.timestamp))
                .order_by(PortLog.id.desc())
                .first()
            )

            if log.event == "arrival":
                transit_seconds = None
                departed_str = None
                if prev_log:
                    # Calculate transit time from previous log (robust)
                    transit_seconds = _seconds_between(
                        log.timestamp, prev_log.timestamp
                    )

                    # Format departure time if previous log exists
                    try:
                        prev_ts = prev_log.timestamp
                        now = datetime.now()
                        if prev_ts.date() == now.date():
                            departed_str = prev_ts.strftime("%H:%M")
                        else:
                            departed_str = prev_ts.strftime("%d %b %H:%M")
                    except Exception:
                        try:
                            departed_str = prev_log.timestamp.replace(
                                microsecond=0
                            ).isoformat()
                        except Exception:
                            departed_str = utc_to_maldives_time(prev_log.timestamp)

                arrivals[log.id] = {
                    "portlog_id": log.id,
                    "vessel_id": vessel.id,
                    "name": vessel.name,
                    "vessel_type": vessel.vessel_type,
                    "contact": vessel.contact,
                    "port_name": log.port.name,
                    "last_port_name": prev_log.port.name if prev_log else None,
                    "event": log.event,
                    "timestamp": utc_to_maldives_time(log.timestamp),
                    "transit_time": _format_duration(transit_seconds),
                    "departed": departed_str,
                }

            elif log.event == "departure":
                # Calculate stay duration if we have a previous arrival at this port
                stay_seconds = None
                if prev_log and prev_log.event == "arrival":
                    try:
                        if prev_log.port.id == log.port.id:
                            stay_seconds = _seconds_between(
                                log.timestamp, prev_log.timestamp
                            )
                    except Exception:
                        stay_seconds = None

                departures[log.id] = {
                    "portlog_id": log.id,
                    "vessel_id": vessel.id,
                    "name": vessel.name,
                    "vessel_type": vessel.vessel_type,
                    "contact": vessel.contact,
                    "port_name": log.port.name,
                    "last_port_name": log.port.name,
                    "event": log.event,
                    "timestamp": utc_to_maldives_time(log.timestamp),
                    "stay_time": _format_duration(stay_seconds),
                }

    return {
        "arrivals": arrivals,
        "departures": departures,
    }


def update_db_with_api(api_key: str, bot_start: bool = False):
    initialize_db()

    all_vessels = api_request(api_key)
    update_port_info(all_vessels)
    update_vessel_info(all_vessels)
    # Check if this is initial sync by seeing if we have any port logs
    is_initial = PortLog.select().count() == 0 or bot_start
    if bot_start:
        PortLogNotification.update(sent=True).execute()
        print("Bot start: Port logs set to sent")
    update_port_logs(all_vessels, is_initial_sync=is_initial)
    return True
