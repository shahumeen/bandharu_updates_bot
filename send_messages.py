from telegram import Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
from datetime import datetime
from zoneinfo import ZoneInfo
import re
import os
from dotenv import load_dotenv
from utils import (
    update_db_with_api,
    all_notify,
)
from model_helpers import (
    User,
    Port,
    PortLog,
    PortLogNotification,
    update_notified,
    get_users_to_notify_for_log,
)

from stats_calculator import get_daily_port_stats
from utils import _seconds_between, _format_duration
from models import Vessel

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


def _format_male_arrival(vessel_id: int, dict: dict, user: User):
    """Format arrival message for Male' with special focus on transit from user's main port.

    Args:
        vessel_id: ID of the arriving vessel
        dict: Dictionary containing vessel arrival info
        user: User object to get their main_port for transit calculation

    Returns:
        Formatted message string if transit info available, None otherwise
    """
    # Only proceed if user has a main port set
    if not user.main_port:
        return None

    vessel = Vessel.get_by_id(vessel_id)
    if not vessel:
        return None

    # Get the last departure from user's main port
    try:
        last_departure = (
            PortLog.select()
            .where(
                PortLog.vessel == vessel_id,
                PortLog.port == user.main_port,
                PortLog.event == "departure",
            )
            .order_by(PortLog.timestamp.desc())
            .first()
        )

        if not last_departure:
            return None

        # Calculate transit time using helper functions
        transit_seconds = _seconds_between(
            dict["arrival_time"], last_departure.timestamp
        )
        transit_time = _format_duration(transit_seconds)
        departure_time = _fmt_time(last_departure.timestamp)
        last_port_name = user.main_port.name

        # Escape special characters for Markdown
        vessel_name = escape_markdown(dict[vessel_id], version=2)
        port_name = escape_markdown(dict["port_name"], version=2)
        vessel_type = escape_markdown(vessel.vessel_type or "Unknown", version=2)
        last_port = escape_markdown(last_port_name, version=2)
        departure = escape_markdown(departure_time, version=2)
        transit = escape_markdown(
            _fmt_time(dict["arrival_time"]) or "Unknown", version=2
        )
        arrival_time = escape_markdown(transit_time or "Unknown", version=2)
        hashtag = re.sub("[^0-9a-zA-Z]+", "", vessel.name).lower()

        # Format the message
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
        print(f"Error formatting Male message: {str(e)}")
        return None


def _format_male_departure(vessel_id: int, dict: dict, user: User):
    """Format arrival message for Male' with special focus on transit from user's main port.

    Args:
        vessel_id: ID of the arriving vessel
        dict: Dictionary containing vessel arrival info
        user: User object to get their main_port for transit calculation

    Returns:
        Formatted message string if transit info available, None otherwise
    """
    # Only proceed if user has a main port set
    if not user.main_port:
        return None

    vessel = Vessel.get_by_id(vessel_id)
    if not vessel:
        return None

    # Get the last departure from user's main port
    try:
        last_departure = (
            PortLog.select()
            .where(
                PortLog.vessel == vessel_id,
                PortLog.port == user.main_port,
                PortLog.event == "departure",
            )
            .order_by(PortLog.timestamp.desc())
            .first()
        )

        if not last_departure:
            return None

        contact = (
            f"\n📞 *Contact:*{dict[vessel_id]["contact"]}"
            if dict[vessel_id]["contact"]
            else ""
        )
        departure_time = _fmt_time(last_departure.timestamp)
        last_port_name = user.main_port.name

        # Escape special characters for Markdown
        vessel_name = escape_markdown(dict[vessel_id], version=2)
        vessel_type = escape_markdown(vessel.vessel_type or "Unknown", version=2)
        last_port = escape_markdown(last_port_name, version=2)
        departure = escape_markdown(departure_time, version=2)
        stay_duration = escape_markdown(
            _fmt_time(dict["stay_time"]) or "Unknown", version=2
        )
        departure_time = escape_markdown(
            (
                _fmt_time(dict[vessel_id].get("timestamp"))
                if dict[vessel_id].get("timestamp")
                else "Unknown"
            ),
            version=2,
        )
        hashtag = re.sub("[^0-9a-zA-Z]+", "", vessel.name).lower()

        # Format the message
        formatted_response = f"""
🟣⚓*[{vessel_name}](m.followme.mv/public/?id={vessel_id}) DEPARTED MALE*⚓
━━━━━━━━━━━━━━━━━━━━━━━
📋 *Type:* {vessel_type}{contact}
📅 *Departed {last_port}:* {departure}
⏳ *Stay Duration:* {stay_duration}
━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
_\\#maledeparture_
"""
        return formatted_response

    except Exception as e:
        print(f"Error formatting Male message: {str(e)}")
        return None


async def arrival_notify(arrivals, context, user: User):
    """Send arrival notifications (arrivals is a dict keyed by portlog id) to a single user/chat."""

    for v in arrivals:
        contact = (
            f"\n📞 *Contact:*{arrivals[v]["contact"]}" if arrivals[v]["contact"] else ""
        )

        island = (
            f'\n🏝️ *Island:* {escape_markdown(arrivals[v]["port_name"], version=2)}'
            if user.chat_type == "private"
            else ""
        )

        vessel_name = escape_markdown(arrivals[v]["name"].upper(), version=2)
        print(vessel_name)
        arrival_time = escape_markdown(
            _fmt_time(arrivals[v].get("timestamp")), version=2
        )
        vessel_type = escape_markdown(
            arrivals[v]["vessel_type"] or "Unknown", version=2
        )
        hashtag = re.sub("[^0-9a-zA-Z]+", "", arrivals[v]["name"]).lower()
        port_hashtag = (
            f'_\\#{re.sub("[^0-9a-zA-Z]+", "", arrivals[v]["port_name"])}_\n'
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

⛵️ *Route:* {route}
📅 *Departed:* {departure_time}
⏳ *Transit Time:* {transit_time}

━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
{port_hashtag}_\\#arrival_
"""
        if (arrivals[v]["port_name"] in male_ports_lst) and user.main_port:
            formatted_response = _format_male_arrival(v, arrivals, user)

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
        print(f"{arrivals[v]['portlog_id']} | status updated to notified for {chat_id}")


async def departures_notify(departures, context, user: User):
    """Send departure notifications (departures is a dict keyed by portlog id) to a single user/chat."""

    for v in departures:
        contact = departures[v].get("contact", None)
        if contact is None:
            contact = ""
        else:
            contact = f"\n📞 *Contact:* {contact}"

        contact = (
            f"\n📞 *Contact:*{departures[v]["contact"]}"
            if departures[v]["contact"]
            else ""
        )
        port_name = (
            f'\n🏝️ *Island:* {escape_markdown(departures[v]["port_name"], version=2)}'
            if user.chat_type == "private"
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
        hashtag = re.sub("[^0-9a-zA-Z]+", "", departures[v]["name"]).lower()
        port_hashtag = (
            f'_\\#{re.sub("[^0-9a-zA-Z]+", "", departures[v]["port_name"])}_\n'
            if user.chat_type == "private"
            else ""
        )
        port_stay = escape_markdown(
            departures[v].get("stay_time") or "Unknown", version=2
        )

        formatted_response = f"""
🔴⚓*[{vessel_name}](m.followme.mv/public/?id={departures[v]["vessel_id"]}) DEPARTED*⚓
━━━━━━━━━━━━━━━━━━━━━━━
{port_name}
⏱️ *Departure Time:* {departure_time}
📋 *Type:* {vessel_type}{contact}
⏳ *Stay Duration:* {port_stay}

━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
{port_hashtag}_\\#departure_
"""
        if (departures[v]["port_name"] in male_ports_lst) and user.main_port:
            formatted_response = _format_male_departure(v, departures, user)

        chat_id = getattr(user, "chat_id", user)
        await context.bot.send_message(
            chat_id=chat_id,
            text=formatted_response,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )

        print(
            f"name:{vessel_name} | type:{vessel_type}\ndepart-time:{departure_time} | stayed:{port_stay} | contact{contact}\n\n"
        )

        update_notified(user, departures[v]["portlog_id"])
        print(
            f"{departures[v]['portlog_id']} | status updated to notified for {chat_id}"
        )


async def notify_job(context):

    print(
        f"{datetime.now(ZoneInfo('Europe/Istanbul')).replace(microsecond=0)} Updating started!\n"
    )

    # 1) Refresh DB from API
    update_db_with_api(FOLLOWME_API_KEY)

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
        f"{datetime.now(ZoneInfo('Europe/Istanbul')).replace(microsecond=0)} Done Updating!\n"
    )
    print("_" * 50 + "\n")
