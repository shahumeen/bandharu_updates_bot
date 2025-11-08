from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown
import re

from model_helpers import Port
from stats_calculator import get_daily_port_stats
from .common import esc_md


async def island_stats(
    update: Update = None, context: ContextTypes.DEFAULT_TYPE = None
):
    # Handle both scheduled and command usage
    chat_id = update.effective_chat.id if update else context._chat_id

    # If no arguments provided, show usage message
    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/islandstats <island_name>`\n"
                "*Example:*\n"
                "`/islandstats Male`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    if not hasattr(context, "args"):
        return  # For scheduled calls without arguments

    port_name = context.args[0].upper()
    # Get matching ports
    matches = list(Port.select().where(Port.name.contains(port_name)).limit(10))

    if not matches:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"😕 No islands found matching ‘{esc_md(port_name)}’\\.",
            parse_mode="MarkdownV2",
        )
        return

    # If multiple matches, show selection keyboard
    if len(matches) > 1:
        keyboard = []
        for port in matches:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        port.name, callback_data=f"get_port_stats:{port.id}"
                    )
                ]
            )

        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔎 Multiple islands found matching ‘{esc_md(port_name)}’\\. Please select one:",
            reply_markup=reply_markup,
            parse_mode="MarkdownV2",
        )
        return

    # Single match found, get stats directly
    port = matches[0]
    await send_port_stats(context, chat_id, port.id)


async def send_port_stats(context, chat_id, port_id):
    try:

        def esc(val):
            return escape_markdown(str(val), version=2)

        stats_dict = get_daily_port_stats(port_id)
        if not stats_dict:
            await context.bot.send_message(
                chat_id=chat_id, text="No statistics available for this port."
            )
            return

        try:
            port = Port.get_by_id(port_id)
            port_name = port.name
        except Port.DoesNotExist:
            port_name = "Unknown Port"

        date = esc(stats_dict["date"])

        # Build busiest hour highlight with tie support
        busiest_highlight = ""
        if (
            stats_dict.get("busiest_hours")
            and len(stats_dict.get("busiest_hours", [])) > 1
        ):
            # Derive the count from any peak hour marked busiest
            busiest_count = None
            for h in stats_dict.get("peak_hours", []):
                if h.get("is_busiest"):
                    busiest_count = h.get("count")
                    break
            if busiest_count is None and stats_dict.get("busiest_hour"):
                busiest_count = None  # can't parse safely; omit count
            hours_str = ", ".join(
                f"{start}-{end}" for start, end in stats_dict.get("busiest_hours", [])
            )
            count_str = (
                f" ({busiest_count} {'vessel' if busiest_count == 1 else 'vessels'})"
                if busiest_count is not None
                else ""
            )
            busiest_text = f"Tie: {hours_str}{count_str}"
            busiest_highlight = f"🏆 _*Busiest Hour:*_\n{esc(busiest_text)}\n"
        elif stats_dict.get("busiest_hour"):
            busiest_highlight = (
                f"🏆 _*Busiest Hour:*_\n{esc(stats_dict['busiest_hour'])}\n"
            )

        # Build longest trip with tie support
        longest_trip_highlight = ""
        if stats_dict.get("longest_trip"):
            lt = stats_dict["longest_trip"]
            if isinstance(lt, dict) and lt.get("tie"):
                longest_trip_highlight = (
                    f"\n🌊 _*Longest Trip:*_\n{esc(lt.get('description', 'Tie'))}\n"
                )
            else:
                longest_trip_highlight = f"\n🌊 _*Longest Trip:*_\n{esc(lt['duration'])} \\- {esc(lt['vessel'])} \\({esc(lt['from'])} → {esc(lt['to'])}\\)\n"

        highlights = (
            f"📈 *{date} HIGHLIGHTS*\n"
            f"────────────────────\n\n"
            + busiest_highlight
            + (
                f"\n🚀 _*Most Active:*_\n{esc(stats_dict['most_active'])}\n"
                if stats_dict.get("most_active")
                else ""
            )
            + longest_trip_highlight
            + (
                f"\n🏝 _*Most Popular Island:*_\n{esc(stats_dict['most_popular_island'])}\n"
                if stats_dict.get("most_popular_island")
                else ""
            )
            + "\n────────────────────\n"
        )

        # Vessel rankings with tie-aware ranks and medals
        medals_by_rank = {1: "🥇", 2: "🥈", 3: "🥉"}
        lines = []
        prev_trips = None
        current_rank = 0
        for entry in stats_dict.get("leaderboard", []):
            trips = entry["trips"]
            if prev_trips is None:
                current_rank = 1
            elif trips < prev_trips:
                current_rank += 1
            prev_trips = trips
            medal = medals_by_rank.get(current_rank, "")
            line = f"{current_rank}\\. {medal} _*{esc(entry['vessel'])}:*_ _{trips} {'trip' if trips==1 else 'trips'}_"
            lines.append(line)
        vessel_rankings = "🎖 *VESSEL RANKINGS*\n" + "\n".join(lines)

        max_count = max(
            (h["count"] for h in stats_dict.get("peak_hours", [])), default=1
        )
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
            + f"\n_\\#dailyreport_ _\\#{date.replace(' ', '')}_ _\\#{re.sub(r'[^0-9a-zA-Z]+', '', port_name)}_ _[How it works](https://telegra.ph/Island-Stats-11-07)_"
        )

        formatted_response = (
            f"{highlights}\n{vessel_rankings}{peak_hours}{daily_totals}"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=formatted_response,
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
    except:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Unable to get stats for _*{port_name}*_\\. Try again later\\.",
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )


async def vessel_stats(
    update: Update = None, context: ContextTypes.DEFAULT_TYPE = None
):
    # Placeholder while feature is in beta
    await context.bot.send_message(
        chat_id=context._chat_id,
        text="🧪 Vessel stats coming soon إن شاء الله",
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )
