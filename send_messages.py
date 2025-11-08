from telegram.helpers import escape_markdown
from telegram.error import Forbidden, BadRequest
from datetime import datetime
from zoneinfo import ZoneInfo
import re
import os
import asyncio
from dotenv import load_dotenv
from utils import all_notify
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
from utils import _seconds_between, _format_duration, utc_to_maldives_time
from models import Vessel
from typing import Optional, Any

load_dotenv()
TOKEN = os.getenv("BOT_API")
FOLLOWME_API_KEY = os.getenv("FOLLOWME_API")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
male_ports_lst = (
    "Male North Harbour",
    "Male South Harbor",
    "Male SW Harbor",
    "Male Harbour",
    "Male Airport Jetty",
)


async def _notify_admin_of_block(chat_id: int, reason: str, context) -> None:
    """Notify admin when a user blocks the bot or the bot is removed from a chat."""
    admin_id = ADMIN_CHAT_ID
    if not admin_id:
        return
    try:
        # Collect some context for admin
        u = User.get_or_none(User.chat_id == chat_id)
        u_name = None
        u_type = None
        if u:
            u_name = u.username or "-"
            u_first_name = u.first_name or "-"
            u_last_name = u.last_name or ""
            u_type = u.chat_type
        msg = (
            f"Notice: cleanup user due to block/kick.\n"
            f"chat_id: {chat_id}\n"
            f"chat_type: {u_type or '-'}\n"
            f"name: {u_first_name} {u_last_name}\n"
            f"username: @{u_name or '-'}\n"
            f"reason: {reason}"
        )
        await context.bot.send_message(chat_id=admin_id, text=msg)
    except Exception:
        # Admin notification is best-effort
        pass


async def _handle_send_failure(chat_id: int, e: Exception, context) -> None:
    """Common handler for send_message failures: detect block/kick, purge user, and notify admin."""
    reason = str(e)
    # Normalize reason string to lowercase for safer matching across locales/wording variants
    reason_l = reason.lower()

    # Explicit block indications (irreversible user-level cases)
    blocked_signals = [
        "bot was blocked by the user",
        "user is deactivated",
    ]

    # Bot removed/kicked/banned or not a member anymore (group/supergroup/channel)
    removed_signals = [
        "bot was kicked from the group chat",
        "bot was kicked from the supergroup chat",
        "bot was kicked from the channel chat",
        "bot was banned from the supergroup chat",
        "bot was banned from the channel chat",
        "bot is not a member of the supergroup chat",
        "bot is not a member of the channel chat",
    ]

    # Ambiguous or permission-related indicators; do NOT auto-delete users/chats
    ambiguous_signals = [
        "chat not found",
        "have no rights",
        "not enough rights",
        "cannot send messages to this chat",
    ]

    should_remove = False
    is_blocked = False
    is_ambiguous = False
    if isinstance(e, Forbidden) or isinstance(e, BadRequest):
        if any(sig in reason_l for sig in blocked_signals):
            should_remove = True
            is_blocked = True
        elif any(sig in reason_l for sig in removed_signals):
            should_remove = True
        elif any(sig in reason_l for sig in ambiguous_signals):
            is_ambiguous = True

    # If we couldn't confidently classify as block/kick/removal, do not delete user.
    # This avoids wiping users on transient permission issues or network errors.
    if not should_remove:
        if is_ambiguous:
            print(
                f"notify skipped for {chat_id}: permission/ambiguous issue detected: {e}",
                flush=True,
            )
        else:
            print(f"unable to notify {chat_id}: {e}")
        return

    # Try to notify user when we believe it's a block/kick. In case of false positives,
    # the user will receive guidance to /start again. If truly blocked, this will fail silently.
    if is_blocked or should_remove:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "It seems you have blocked me. If this is wrong please send /start to begin."
                ),
            )
        except Exception:
            pass

    # Capture details before deletion for admin message
    try:
        await _notify_admin_of_block(chat_id, reason, context)
    except Exception:
        pass

    # Remove user from database ONLY when we confidently detect block/kick/removal
    try:
        u = User.get_or_none(User.chat_id == chat_id)
        if u:
            u.delete_instance(recursive=True)
            print(
                f"[cleanup] Removed user {chat_id} due to block/kick: {reason}",
                flush=True,
            )
    except Exception as purge_err:
        print(
            f"[cleanup] Failed to remove user {chat_id}: {purge_err}",
            flush=True,
        )


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
        # Parse current event timestamp
        current_ts = _ensure_datetime(event.get("timestamp"))

        # Last ARRIVAL to the user's main port before current Male arrival
        last_user_arrival = (
            PortLog.select()
            .where(
                (PortLog.vessel == vessel_id)
                & (PortLog.port == user.main_port)
                & (PortLog.event == "arrival")
                & (PortLog.timestamp < current_ts)
            )
            .order_by(PortLog.timestamp.desc())
            .first()
        )

        # Check if there was a previous Male ARRIVAL after the last user.main_port arrival
        # and before this current Male arrival. If yes, suppress the "from_island" details.
        suppress_from_island = False
        if last_user_arrival and current_ts:
            suppress_from_island = (
                PortLog.select()
                .join(Port)
                .where(
                    (PortLog.vessel == vessel_id)
                    & (PortLog.event == "arrival")
                    & (Port.name.in_(male_ports_lst))
                    & (PortLog.timestamp > last_user_arrival.timestamp)
                    & (PortLog.timestamp < current_ts)
                )
                .exists()
            )

        # Last DEPARTURE from the user's main port (used for transit calc)
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
        contact = f"\n📞 *Contact:* {event['contact']}" if event['contact'] else ""

        if not suppress_from_island and last_departure:
            # Calculate transit from user's main port departure to this arrival
            transit_seconds = _seconds_between(
                event.get("timestamp"), last_departure.timestamp
            )
            transit_fmt = _format_duration(transit_seconds) or "Unknown"
            departure_time_fmt = _fmt_time(
                utc_to_maldives_time(last_departure.timestamp)
            )
            departure = escape_markdown(departure_time_fmt, version=2)
            transit = escape_markdown(transit_fmt, version=2)
        else:
            departure = None
            transit = None

        # Escape for MarkdownV2
        vessel_name = escape_markdown(event.get("name", "Unknown"), version=2)
        port_name = escape_markdown(event.get("port_name", "Unknown"), version=2)
        vessel_type = escape_markdown(event["vessel_type"] or "Unknown", version=2)
        last_port = escape_markdown(user.main_port.name, version=2)

        arrival_time = escape_markdown(
            _fmt_time(utc_to_maldives_time(event.get("timestamp"))), version=2
        )

        hashtag = re.sub(r"[^0-9a-zA-Z]+", "", vessel.name).lower()
        # Only include the from_island block if we didn't suppress it and we have values
        if not suppress_from_island and departure is not None and transit is not None:
            from_island = f"\n📅 *Departed {last_port}:* {departure}\n⏳ *Transit Time:* {transit}"
        else:
            from_island = ""

        formatted_response = f"""
🔵⚓*[{vessel_name}](m.followme.mv/public/?id={vessel_id}) ARRIVED MALE*⚓
━━━━━━━━━━━━━━━━━━━━━━━
📍 *Location:* {port_name}
⏱️ *Arrival Time:* {arrival_time}
📋 *Type:* {vessel_type}{contact}{from_island}
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
        contact = f"\n📞 *Contact:* {contact_val}" if contact_val else ""

        # Escape special characters for Markdown
        vessel_name = escape_markdown(event.get("name", "Unknown"), version=2)
        vessel_type = escape_markdown(event["vessel_type"] or "Unknown", version=2)
        last_port = escape_markdown(event.get("port_name"), version=2)
        stay_duration = escape_markdown(
            (event.get("stay_time") or "Unknown"), version=2
        )
        departure_time = escape_markdown(
            (
                _fmt_time(event.get("timestamp"))
                if event.get("timestamp")
                else "Unknown"
            ),
            version=2,
        )
        hashtag = re.sub(r"[^0-9a-zA-Z]+", "", vessel.name).lower()

        formatted_response = f"""
🟣⚓*[{vessel_name}](m.followme.mv/public/?id={vessel_id}) DEPARTED MALE*⚓
━━━━━━━━━━━━━━━━━━━━━━━
📍 *Departed from:* {last_port}
⏱️ *Departure Time:* {departure_time}
📋 *Type:* {vessel_type}{contact}
⏳ *Stay Duration:* {stay_duration}
━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
_\\#maledeparture_
"""
        return formatted_response
    except Exception as e:
        print(f"Error formatting Male message: {str(e)}", flush=True)
        return None


RATE_LIMIT_DELAY = 0.04  # seconds -> 25 messages / second max


async def arrival_notify(arrivals, context, user: User):
    """Send arrival notifications (arrivals is a dict keyed by portlog id) to a single user/chat."""

    for v in arrivals:
        contact = (
            f"\n📞 *Contact:* {arrivals[v]['contact']}"
            if arrivals[v]['contact']
            else ""
        )

        island = (
            f'📍 *Location:* {escape_markdown(arrivals[v]["port_name"], version=2)}\n'
            if user.chat_type in ("private", "group")
            else ""
        )

        vessel_name = escape_markdown(arrivals[v]["name"].upper(), version=2)
        arrival_time = escape_markdown(
            _fmt_time(utc_to_maldives_time(arrivals[v].get("timestamp"))), version=2
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

        formatted_response = f"""
🟢⚓*[{vessel_name}](m.followme.mv/public/?id={vessel_id}) ARRIVED*⚓
━━━━━━━━━━━━━━━━━━━━━━━
{island}⏱️ *Arrival Time:* {arrival_time}
📋 *Type:* {vessel_type}{contact}

🗺 *Route:* {route}
📅 *Departed:* {departure_time}
⏳ *Transit Time:* {transit_time}
━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
{port_hashtag}_\\#arrival_
"""
        # Apply Male-specific formatting only if user's main_port is NOT a Male port
        if arrivals[v]["port_name"] in male_ports_lst:
            if user.main_port and (user.main_port.name not in male_ports_lst):
                male_msg = _format_male_arrival(arrivals[v], user)
                if male_msg:
                    formatted_response = male_msg

        chat_id = user.chat_id
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=formatted_response,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            update_notified(user, int(arrivals[v]["portlog_id"]))
        except Exception as e:
            await _handle_send_failure(chat_id, e, context)
        # Throttle to respect global rate limits (similar to /broadcast admin command)
        await asyncio.sleep(RATE_LIMIT_DELAY)


async def departures_notify(departures, context, user: User):
    """Send departure notifications (departures is a dict keyed by portlog id) to a single user/chat."""

    for v in departures:
        chat_id = user.chat_id
        if not user.notify_on_departure:
            update_notified(user, int(departures[v]["portlog_id"]))
            print(
                f"{departures[v]['portlog_id']} | status updated to notified for {chat_id}",
                flush=True,
            )
            continue

        contact = departures[v].get("contact", None)
        if contact is None:
            contact = ""
        else:
            contact = f"\n📞 *Contact:* {contact}"

        contact = (
            f"\n📞 *Contact:* {departures[v]['contact']}"
            if departures[v]['contact']
            else ""
        )
        island = (
            f'📍 *Location:* {escape_markdown(departures[v]["port_name"], version=2)}\n'
            if user.chat_type in ("private", "group")
            else ""
        )

        vessel_name = escape_markdown(departures[v]["name"].upper(), version=2)
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
🔴⚓*[{vessel_name}](m.followme.mv/public/?id={vessel_id}) DEPARTED*⚓
━━━━━━━━━━━━━━━━━━━━━━━
{island}⏱️ *Departure Time:* {departure_time}
📋 *Type:* {vessel_type}{contact}
⏳ *Stay Duration:* {port_stay}
━━━━━━━━━━━━━━━━━━━━━━━
_\\#{hashtag}_
{port_hashtag}_\\#departure_
"""
        # Apply Male-specific formatting only if user's main_port is NOT a Male port
        if departures[v]["port_name"] in male_ports_lst:
            if user.main_port and (user.main_port.name not in male_ports_lst):
                male_msg = _format_male_departure(departures[v], user)
                if male_msg:
                    formatted_response = male_msg
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=formatted_response,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            update_notified(user, int(departures[v]["portlog_id"]))
        except Exception as e:
            await _handle_send_failure(chat_id, e, context)
        # Throttle send rate
        await asyncio.sleep(RATE_LIMIT_DELAY)


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
