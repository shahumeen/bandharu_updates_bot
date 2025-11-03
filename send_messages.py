from telegram.helpers import escape_markdown
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import re
import os
from dotenv import load_dotenv
from utils import (
    all_notify
)
from model_helpers import (
    update_notified,
    get_users_to_notify_for_log,
)
from models import (
    User,
    PortLog,
    PortLogNotification,
    Port,
)
from utils import _seconds_between, _format_duration
from models import Vessel
from typing import Optional, List, Any

load_dotenv()
TOKEN = os.getenv("BOT_API")
CHANNEL_ID = os.getenv("CHANNEL_ID")
FOLLOWME_API_KEY = os.getenv("FOLLOWME_API")
PORT_NAME = os.getenv("PORT_NAME")
male_ports_lst = [
    "Male North Harbour",
    "Male South Harbor",
    "Male SW Harbor",
    "Male Harbour",
    "Male Airport Jetty",
]


def _fmt_time(ts):
    try:
        if hasattr(ts, "strftime"):
            return ts.strftime("%H:%M")
        if isinstance(ts, (int, float)):
            # Convert to minutes
            total_minutes = int(ts)
            days = total_minutes // (24 * 60)
            hours = (total_minutes % (24 * 60)) // 60
            minutes = total_minutes % 60

            parts = []
            if days > 0:
                parts.append(f"{days}d")
            if hours > 0 or days > 0:
                parts.append(f"{hours}h")
            parts.append(f"{minutes}m")

            return "".join(parts)

        s = str(ts)
        if " " in s:
            return s.split()[1][:5]
        return s
    except Exception:
        return "Unknown"


def _ensure_datetime(ts: Any) -> Optional[datetime]:
    """Best-effort convert a timestamp-like value to datetime.

    Accepts datetime or ISO-like string; returns None if parsing fails.
    """
    if isinstance(ts, datetime):
        return ts
    if ts is None:
        return None
    try:
        # Attempt ISO parsing; fall back to str() + fromisoformat
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None


def _has_recent_event(
    vessel_id: int,
    event: str,
    current_ts: Any,
    within_hours: int = 5,
    restrict_port_names: Optional[List[str]] = None,
) -> bool:
    """Return True if the vessel has an event of type `event` within the last `within_hours` hours
    before `current_ts`. If `restrict_port_names` is provided, only consider logs whose Port.name is in
    that list (case-sensitive match to stored names).
    """
    ts = _ensure_datetime(current_ts)
    if not ts:
        return False

    window_start = ts - timedelta(hours=within_hours)

    base_condition = (
        (PortLog.vessel == vessel_id)
        & (PortLog.event == event)
        & (PortLog.timestamp >= window_start)
        & (PortLog.timestamp < ts)
    )

    try:
        if restrict_port_names:
            q = (
                PortLog.select()
                .join(Port)
                .where(base_condition & (Port.name.in_(restrict_port_names)))
            )
        else:
            q = PortLog.select().where(base_condition)

        return q.exists()
    except Exception:
        return False


def _format_male_arrival(event: dict, user: User):
    """Format Male' arrival message focusing on transit from the user's main port.

    Expects a single event payload with keys from utils.all_notify()['arrivals'][id].
    """
    # Only proceed if user has a main port set
    if not user.main_port:
        return None

    try:
        vessel_id = int(event.get("vessel_id"))
    except Exception:
        return None

    # Be tolerant if vessel is missing in DB
    vessel = Vessel.get_or_none(Vessel.id == vessel_id)
    if not vessel:
        return None

    try:
        # Last departure from the user's main port
        last_departure = (
            PortLog.select()
            .where(
                (PortLog.vessel == vessel_id)
                & (PortLog.port == user.main_port)
                & (PortLog.event == "departure")
            )
            .order_by(PortLog.timestamp.desc())
            .first()
        )

        if not last_departure:
            return None

        # Calculate transit from user's main port departure to this arrival
        transit_seconds = _seconds_between(
            event.get("timestamp"), last_departure.timestamp
        )
        transit_fmt = _format_duration(transit_seconds) or "Unknown"
        arrival_time_fmt = _fmt_time(event.get("timestamp"))
        departure_time_fmt = _fmt_time(last_departure.timestamp)

        # Escape for MarkdownV2
        vessel_name = escape_markdown(event.get("name", "Unknown"), version=2)
        port_name = escape_markdown(event.get("port_name", "Unknown"), version=2)
        vessel_type = escape_markdown(vessel.vessel_type or "Unknown", version=2)
        last_port = escape_markdown(user.main_port.name, version=2)
        departure = escape_markdown(departure_time_fmt, version=2)
        arrival_time = escape_markdown(arrival_time_fmt or "Unknown", version=2)
        transit = escape_markdown(transit_fmt, version=2)
        hashtag = re.sub(r"[^0-9a-zA-Z]+", "", vessel.name).lower()

        formatted_response = f"""
🔵⚓*[{vessel_name}](m.followme.mv/public/?id={vessel_id}) ARRIVED MALE*⚓
━━━━━━━━━━━━━━━━━━━━━━━
📍 *Location:* {port_name}
⏱️ *Arrival Time:* {arrival_time}
📋 *Type:* {vessel_type}

📅 *Departed {last_port}:* {departure}
⏳ *Transit Time:* {transit}
━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
_\\#malearrival_
"""
        return formatted_response
    except Exception as e:
        print(f"Error formatting Male message: {str(e)}", flush=True)
        return None


def _format_male_departure(event: dict, user: User):
    """Format Male' departure message, including stay duration if available."""
    if not user.main_port:
        return None

    try:
        vessel_id = int(event.get("vessel_id"))
    except Exception:
        return None

    vessel = Vessel.get_or_none(Vessel.id == vessel_id)
    if not vessel:
        return None

    try:


        contact_val = event.get("contact")
        contact = f"\n📞 *Contact:*{contact_val}" if contact_val else ""

        # Escape special characters for Markdown
        vessel_name = escape_markdown(event.get("name", "Unknown"), version=2)
        vessel_type = escape_markdown(vessel.vessel_type or "Unknown", version=2)
        last_port = escape_markdown(event.get("port_name"), version=2)
        stay_duration = escape_markdown(
            (event.get("stay_time") or "Unknown"), version=2
        )
        hashtag = re.sub(r"[^0-9a-zA-Z]+", "", vessel.name).lower()

        formatted_response = f"""
🟣⚓*[{vessel_name}](m.followme.mv/public/?id={vessel_id}) DEPARTED MALE*⚓
━━━━━━━━━━━━━━━━━━━━━━━
📋 *Type:* {vessel_type}{contact}
📅 *Departed from:* {last_port}
⏳ *Stay Duration:* {stay_duration}
━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
_\\#maledeparture_
"""
        return formatted_response
    except Exception as e:
        print(f"Error formatting Male message: {str(e)}", flush=True)
        return None


async def arrival_notify(arrivals, context, user: User):
    """Send arrival notifications (arrivals is a dict keyed by portlog id) to a single user/chat."""

    for v in arrivals:
        contact = (
            f"\n📞 *Contact:*{arrivals[v]['contact']}" if arrivals[v]['contact'] else ""
        )

        island = (
            f'\n📍 *Location:* {escape_markdown(arrivals[v]["port_name"], version=2)}'
            if user.chat_type in ("private", "group")
            else ""
        )

        vessel_name = escape_markdown(arrivals[v]["name"].upper(), version=2)
        arrival_time = escape_markdown(
            _fmt_time(arrivals[v].get("timestamp")), version=2
        )
        vessel_type = escape_markdown(
            arrivals[v]["vessel_type"] or "Unknown", version=2
        )
        hashtag = re.sub(r"[^0-9a-zA-Z]+", "", arrivals[v]["name"]).lower()
        port_hashtag = (
            f'_\\#{re.sub(r"[^0-9a-zA-Z]+", "", arrivals[v]["port_name"])}_\n'
            if user.chat_type == "private"
            else ""
        )

        transit_time = escape_markdown(
            arrivals[v].get("transit_time") or "Unknown", version=2
        )
        departure_time = escape_markdown(
            (
                _fmt_time(arrivals[v].get("departed"))
                if arrivals[v].get("departed")
                else "Unknown"
            ),
            version=2,
        )
        last_port_name = arrivals[v]["last_port_name"]
        route = escape_markdown(
            (last_port_name or "Unknown")
            + " → "
            + (arrivals[v]["port_name"] or "Unknown"),
            version=2,
        )
        vessel_id = arrivals[v]["vessel_id"]
        header = (
            f"🟢⚓*[{vessel_name}](m.followme.mv/public/?id={vessel_id}) ARRIVED*⚓"
        )

        formatted_response = f"""
{header}
━━━━━━━━━━━━━━━━━━━━━━━
{island}
⏱️ *Arrival Time:* {arrival_time}
📋 *Type:* {vessel_type}{contact}

🗺 *Route:* {route}
📅 *Departed:* {departure_time}
⏳ *Transit Time:* {transit_time}

━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
{port_hashtag}_\\#arrival_
"""
        # Apply Male-specific formatting only if user's main_port is NOT a Male port
        if (
            (arrivals[v]["port_name"] in male_ports_lst)
            and user.main_port
            and (user.main_port.name not in male_ports_lst)
        ):
            # If there's already a Male arrival for this vessel within the last 5 hours, skip notifying.
            if _has_recent_event(
                vessel_id,
                "arrival",
                arrivals[v].get("timestamp"),
                within_hours=5,
                restrict_port_names=male_ports_lst,
            ):
                update_notified(user, arrivals[v]["portlog_id"])
                continue
            male_msg = _format_male_arrival(arrivals[v], user)
            if male_msg:
                formatted_response = male_msg

        chat_id = getattr(user, "chat_id", user)
        await context.bot.send_message(
            chat_id=chat_id,
            text=formatted_response,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )

        print(
            f"name:{vessel_name} | type:{vessel_type}\ndepart-time:{arrival_time}\ncontact{contact}\n\n"
        )
        update_notified(user, arrivals[v]["portlog_id"])
        print(
            f"{arrivals[v]['portlog_id']} | status updated to notified for {chat_id}",
            flush=True,
        )


async def departures_notify(departures, context, user: User):
    """Send departure notifications (departures is a dict keyed by portlog id) to a single user/chat."""

    for v in departures:
        contact = departures[v].get("contact", None)
        if contact is None:
            contact = ""
        else:
            contact = f"\n📞 *Contact:* {contact}"

        contact = (
            f"\n📞 *Contact:*{departures[v]['contact']}"
            if departures[v]['contact']
            else ""
        )
        island = (
            f'\n📍 *Location:* {escape_markdown(arrivals[v]["port_name"], version=2)}'
            if user.chat_type in ("private", "group")
            else ""
        )

        vessel_name = escape_markdown(departures[v]["name"].upper(), version=2)
        print(vessel_name)
        departure_time = escape_markdown(
            (
                _fmt_time(departures[v].get("timestamp"))
                if departures[v].get("timestamp")
                else "Unknown"
            ),
            version=2,
        )
        vessel_type = escape_markdown(
            departures[v]["vessel_type"] or "Unknown", version=2
        )
        hashtag = re.sub(r"[^0-9a-zA-Z]+", "", departures[v]["name"]).lower()
        port_hashtag = (
            f'_\\#{re.sub(r"[^0-9a-zA-Z]+", "", departures[v]["port_name"])}_\n'
            if user.chat_type == "private"
            else ""
        )
        port_stay = escape_markdown(
            departures[v].get("stay_time") or "Unknown", version=2
        )
        vessel_id = departures[v]["vessel_id"]

        formatted_response = f"""
🔴⚓*[{vessel_name}](m.followme.mv/public/?id={departures[v]["vessel_id"]}) DEPARTED*⚓
━━━━━━━━━━━━━━━━━━━━━━━
{island}
⏱️ *Departure Time:* {departure_time}
📋 *Type:* {vessel_type}{contact}
⏳ *Stay Duration:* {port_stay}

━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
{port_hashtag}_\\#departure_
"""
        # Apply Male-specific formatting only if user's main_port is NOT a Male port
        if (
            (departures[v]["port_name"] in male_ports_lst)
            and user.main_port
            and (user.main_port.name not in male_ports_lst)
        ):
            # If there's already a Male departure for this vessel within the last 5 hours, skip notifying.
            if _has_recent_event(
                vessel_id,
                "departure",
                departures[v].get("timestamp"),
                within_hours=5,
                restrict_port_names=male_ports_lst,
            ):
                update_notified(user, departures[v]["portlog_id"])
                continue
            male_msg = _format_male_departure(departures[v], user)
            if male_msg:
                formatted_response = male_msg

        chat_id = getattr(user, "chat_id", user)
        await context.bot.send_message(
            chat_id=chat_id,
            text=formatted_response,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )

        print(
            f"name:{vessel_name} | type:{vessel_type}\ndepart-time:{departure_time} | stayed:{port_stay} | contact{contact}\n\n",
            flush=True,
        )

        update_notified(user, departures[v]["portlog_id"])
        print(
            f"{departures[v]['portlog_id']} | status updated to notified for {chat_id}",
            flush=True,
        )


async def notify_job(context):

    print(
        f"{datetime.now(ZoneInfo('Europe/Istanbul')).replace(microsecond=0)} Updating started!\n",
        flush=True,
    )

    # 1) Refresh DB from API
    # update_db_with_api(FOLLOWME_API_KEY)

    # 2) Collect all un-notified port logs grouped as arrivals/departures
    updates = all_notify()
    arrivals = updates.get("arrivals", {}) or {}
    departures = updates.get("departures", {}) or {}

    # 3) For each arrival log, find recipients and notify them individually
    for log_id, payload in arrivals.items():
        try:
            port_log = PortLog.get_by_id(log_id)
        except Exception:
            continue

        recipients = get_users_to_notify_for_log(port_log)
        for user in recipients:
            # pass a single-entry dict to the notifier (it expects a dict keyed by id)
            await arrival_notify({log_id: payload}, context, user)

        # if everyone has been notified (no pending PortLogNotification.sent==False), mark global flag
        pending = (
            PortLogNotification.select()
            .where(
                (PortLogNotification.port_log == port_log)
                & (PortLogNotification.sent == False)
            )
            .count()
        )
        if pending == 0:
            try:
                port_log.notified = True
                port_log.save()
            except Exception:
                pass

    # 4) For departures
    for log_id, payload in departures.items():
        try:
            port_log = PortLog.get_by_id(log_id)
        except Exception:
            continue

        recipients = get_users_to_notify_for_log(port_log)
        for user in recipients:
            await departures_notify({log_id: payload}, context, user)

        pending = (
            PortLogNotification.select()
            .where(
                (PortLogNotification.port_log == port_log)
                & (PortLogNotification.sent == False)
            )
            .count()
        )
        if pending == 0:
            try:
                port_log.notified = True
                port_log.save()
            except Exception:
                pass

    print(
        f"{datetime.now(ZoneInfo('Europe/Istanbul')).replace(microsecond=0)} Done Updating!\n",
        flush=True,
    )
    print("_" * 50 + "\n", flush=True)
