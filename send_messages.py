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
from utils import _fmt_time, _format_male

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


async def arrival_notify(arrivals, context, user: User):
    """Send arrival notifications (arrivals is a dict keyed by portlog id) to a single user/chat."""

    for v in arrivals:
        contact = (
            f"\n📞 *Contact:*{arrivals[v]["contact"]}" if arrivals[v]["contact"] else ""
        )

        port_name = (
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
            f'_\\#{re.sub("[^0-9a-zA-Z]+", "", arrivals[v]["port_name"]).replace('.', '_').lower()}_\n'
            if user.chat_type == "private"
            else ""
        )

        transit_time = escape_markdown(
            arrivals[v].get("transit_time") or "Unknown", version=2
        )
        departure_time = escape_markdown(
            (
                _fmt_time(arrivals[v].get("timestamp"))
                if arrivals[v].get("timestamp")
                else "Unknown"
            ),
            version=2,
        )
        last_port_name = arrivals[v]["last_port_name"]
        route = escape_markdown(
            ("⛵️ *Route:*\n")
            + (last_port_name or "Unknown")
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
{port_name}
⏱️ *Arrival Time:* {arrival_time}
📋 *Type:* {vessel_type}{contact}

{route}
📅 *Departed:* {departure_time}
⏳ *Transit:* {transit_time}

━━━━━━━━━━━━━━━━━━━━━━━
{port_hashtag}_\\#{hashtag}_
_\\#arrival_
"""
        if port_name in male_ports_lst:
            formatted_response = _format_male(v, arrivals, user)

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
            f'_\\#{re.sub("[^0-9a-zA-Z]+", "", departures[v]["port_name"]).replace('.','_').lower()}_\n'
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
{port_hashtag}_\\#{hashtag}_
_\\#departure_
"""

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


async def male_arrival_notify(mle_arrivals, context, user: User):
    """Send special Male arrival notifications to a single user/chat."""

    def _fmt_time(ts):
        try:
            if hasattr(ts, "strftime"):
                return ts.strftime("%H:%M")
            s = str(ts)
            if " " in s:
                return s.split()[1][:5]
            return s
        except Exception:
            return "Unknown"

    for v in mle_arrivals:
        contact = mle_arrivals[v].get("contact", None)
        if contact is None:
            contact = ""
        else:
            contact = f"\n📞 *Contact:* {contact}"

        vessel_name = escape_markdown(mle_arrivals[v]["name"].upper(), version=2)
        print(vessel_name)
        arrival_time = escape_markdown(
            (
                _fmt_time(mle_arrivals[v].get("timestamp"))
                if mle_arrivals[v].get("timestamp")
                else "Unknown"
            ),
            version=2,
        )
        vessel_type = escape_markdown(
            mle_arrivals[v]["vessel_type"] or "Unknown", version=2
        )
        hashtag = re.sub("[^0-9a-zA-Z]+", "", mle_arrivals[v]["name"]).lower()
        route = escape_markdown(
            PORT_NAME + " → " + (mle_arrivals[v].get("to_port_name") or "Unknown"),
            version=2,
        )
        transit_time = escape_markdown(
            mle_arrivals[v].get("transit_time") or "Unknown", version=2
        )
        departure_time = escape_markdown(
            mle_arrivals[v].get("departed") or "Unknown", version=2
        )
        port = escape_markdown(PORT_NAME, version=2)

        formatted_response = f"""
🔵⚓*[{vessel_name}](m.followme.mv/public/?id={mle_arrivals[v]['vessel_id']}) ARRIVED MALÉ*⚓
_________________________

⏱️ *Arrival Time:* {arrival_time}
📋 *Type:* {vessel_type}{contact}

⛵️ *Route:*
{route}
📅 *Left {port}:* {departure_time}
⏳ *Transit:* {transit_time}

_________________________
_\\#{hashtag}_
_\\#malearrival_
"""

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
        update_notified(user, mle_arrivals[v]["portlog_id"])
        print(
            f"{mle_arrivals[v]['portlog_id']} | status updated to notified for {chat_id}"
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


async def daily_stats(update: Update = None, context: ContextTypes.DEFAULT_TYPE = None):
    # Handle both scheduled and command usage
    port_name = context.args[0].upper()

    def get_port_id():
        if context and hasattr(context, "args") and context.args:
            port = Port.get_or_none(Port.name.contains(port_name))
            if not port:
                return None, f'Port with name "{port_name}" not found.'
            return port.id, None
        return None, f"Please type a port name to get stats!"

    target_port_id, error = get_port_id()
    if error:
        await update.message.reply_text(error)
        return

    def esc(val):
        return escape_markdown(str(val), version=2)

    stats_dict = get_daily_port_stats(target_port_id)
    date = esc(stats_dict["date"])

    highlights = (
        f"📈 *{date} HIGHLIGHTS*\n"
        f"────────────────────\n\n"
        + (
            f"🏆 _*Busiest Hour:*_\n{esc(stats_dict['busiest_hour'])}\n"
            if stats_dict.get("busiest_hour")
            else ""
        )
        + (
            f"\n🚀 _*Most Active:*_\n{esc(stats_dict['most_active'])}\n"
            if stats_dict.get("most_active")
            else ""
        )
        + (
            f"\n🌊 _*Longest Trip:*_\n{esc(stats_dict['longest_trip']['duration'])} \\- {esc(stats_dict['longest_trip']['vessel'])} \\({esc(stats_dict['longest_trip']['from'])} → {esc(stats_dict['longest_trip']['to'])}\\)\n"
            if stats_dict.get("longest_trip")
            else ""
        )
        + (
            f"\n🏝 _*Most Popular Island:*_\n{esc(stats_dict['most_popular_island'])}\n"
            if stats_dict.get("most_popular_island")
            else ""
        )
        + "\n────────────────────\n"
    )

    medals = ["🥇", "🥈", "🥉"]
    vessel_rankings = "🎖 *VESSEL RANKINGS*\n" + "\n".join(
        f"{i+1}\\. {medals[i]} _*{esc(entry['vessel'])}:*_ _{entry['trips']} {'trip' if entry['trips']==1 else 'trips'}_"
        for i, entry in enumerate(stats_dict.get("leaderboard", []))
    )

    max_count = max((h["count"] for h in stats_dict.get("peak_hours", [])), default=1)
    peak_hours = "\n\n⏱️*PEAK HOURS*\n" + "\n".join(
        f" {esc(h['hour'])} {'█' * int((h['count']/max_count)*10)} {h['count']} {esc(h['vessel_word'])}{' 🏆' if h.get('is_busiest') else ''}"
        for h in stats_dict.get("peak_hours", [])
    )

    daily_totals = (
        "\n\n📊 *DAILY TOTALS*\n"
        f"• *Total Trips:* {esc(stats_dict['total_trips'])}\n"
        f"• *Unique Vessels:* {esc(stats_dict['unique_vessels'])}\n"
        + "\n".join(
            f"• *{esc(vtype)}:* {count} {'trip' if count==1 else 'trips'}"
            for vtype, count in stats_dict.get("vessel_type_trips", {}).items()
        )
        + "\n\n────────────────────"
        + f"\n \\#dailyreport \\#{date.replace(" ", "_")} \\#{re.sub("[^0-9a-zA-Z]+", "", Port.get_or_none(Port.name.contains(port_name)).name)}"
    )

    formatted_response = f"{highlights}\n{vessel_rankings}{peak_hours}{daily_totals}"
    print(formatted_response)
    await context.bot.send_message(
        chat_id=context._chat_id,
        text=formatted_response,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )

    print("Success")
