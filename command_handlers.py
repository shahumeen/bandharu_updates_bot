from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
)
from telegram.helpers import escape_markdown
import re
from peewee import JOIN
from model_helpers import (
    Port,
    Vessel,
    User,
    create_user,
    subscribe_user_to_port,
    subscribe_user_to_vessel,
    get_user_subscriptions,
    unsubscribe_user_from_port,
    unsubscribe_user_from_vessel,
    set_main_port,
)
import os
from dotenv import load_dotenv
from stats_calculator import get_daily_port_stats

load_dotenv()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

# Small helper for MarkdownV2 escaping
def esc_md(value) -> str:
    return escape_markdown(str(value), version=2)
### --- User command handlers ---


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id

    # For groups/channels, ensure the chat itself exists as a user record
    if chat.type in ["group", "supergroup", "channel"]:
        try:
            create_user(
                telegram_id=chat_id,
                chat_type=chat.type,
                username=None,
                first_name=chat.title,
                last_name=None,
            )
        except Exception:
            # ignore DB errors for start
            pass
    # For private chats, use the actual user info
    elif user:
        try:
            create_user(
                telegram_id=chat_id,
                chat_type=chat.type,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )
        except Exception:
            # ignore DB errors for start
            pass

    text = (
        "*👋 Welcome to Bandharu Updates Bot*\n\n"
        "Stay notified about islands and vessels you care about\\.") + "\n\n" + (
        "🧭 *Quick commands:*\n"
        "• */addisland* \\<name\\> \\- Subscribe to an island/port 🏝\n"
        "• */addvessel* \\<name or id\\> \\- Subscribe to a vessel ⛴\n"
        "• */settings* \\- View your subscriptions ⚙️\n"
        "• */unsub* \\- Manage and remove subscriptions 🔕\n"
        "• */islandstats* \\<island\\> \\- Today’s stats 📊\n"
        "• */vesselstats* \\<vessel\\> \\- Vessel stats \\(beta\\) 🧪\n\n"
        f"Island update channels: ['BandharuUpdates']('https://t.me/addlist/ziV1Htn9OR9iNWI1')") + "\n" + (
        "👾 Uses FollowMe\\.mv API"
    )
    await context.bot.send_message(
        chat_id=chat_id, text=text, parse_mode="MarkdownV2", disable_web_page_preview=True
    )


async def unrecognized_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle any messages that are not commands."""
    await update.message.reply_text(
        "🤖 I couldn’t recognize that\\. Try */start* for a list of commands\\.",
        parse_mode="MarkdownV2",
    )


async def subisland(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe user to a port (island). If multiple matches are found show inline options."""
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id

    # For groups/channels, ensure the chat itself exists as a user record
    if chat.type in ["group", "supergroup", "channel"]:
        try:
            create_user(
                telegram_id=chat_id,
                chat_type=chat.type,
                username=None,
                first_name=chat.title,
                last_name=None,
            )
        except Exception:
            pass
    # For private chats, use the actual user info
    elif user:
        try:
            create_user(
                telegram_id=chat_id,
                chat_type=chat.type,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )
        except Exception:
            pass

    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*🏝 Add an island*\n"
                "Use: */addisland* \\<island name\\>\n"
                "Example: */addisland* Male\n\n"
                "Pro tip: You can type part of the name and I’ll show matches\\. 🔎"
            ),
            parse_mode="MarkdownV2",
        )
        return

    name = " ".join(context.args).strip()

    # Get all matching ports and user's current subscriptions
    matches = list(Port.select().where(Port.name.contains(name)).limit(10))
    subs = get_user_subscriptions(chat_id)
    subbed_ports = {p.id: p for p in subs.get("ports", [])}

    if not matches:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"😕 No islands found matching ‘{esc_md(name)}’\\. Try a shorter part of the name\\.",
            parse_mode="MarkdownV2",
        )
        return

    # Split matches into already subscribed and available
    already_subbed = []
    available = []
    for p in matches:
        if p.id in subbed_ports:
            already_subbed.append(p)
        else:
            available.append(p)

    # If only one match and already subscribed
    if len(matches) == 1 and matches[0].id in subbed_ports:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔔 You’re already subscribed to {esc_md(matches[0].name)}\.",
            parse_mode="MarkdownV2",
        )
        return

    # If only one match and not subscribed
    if len(matches) == 1:
        port = matches[0]
        sub, created, err = subscribe_user_to_port(chat_id, port.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Subscribed to {esc_md(port.name)}\\! You’ll get updates as they happen\\.",
                parse_mode="MarkdownV2",
            )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ You’ve reached the maximum of 10 island subscriptions\\. Remove one with */unsub* to add more\\.",
                    parse_mode="MarkdownV2",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Failed to subscribe to {esc_md(port.name)}\\. Please try again shortly\\.",
                    parse_mode="MarkdownV2",
                )
        return

    # Show already subscribed ports first
    msg_parts = []
    if already_subbed:
        msg_parts.append("*🔔 Already subscribed:*")
        for p in already_subbed:
            msg_parts.append(f"• {esc_md(p.name)}")

    # Then show keyboard for available ones
    keyboard = []
    for p in available:
        keyboard.append(
            [InlineKeyboardButton(p.name, callback_data=f"sub_port:{p.id}")]
        )

    if not keyboard:
        # All matches are already subscribed
        await context.bot.send_message(
            chat_id=chat_id, text="\n".join(msg_parts), parse_mode="MarkdownV2"
        )
        return

    msg = (
        "\n".join(msg_parts + ["", "*➕ Available islands to subscribe:*"])
        if msg_parts
        else "*➕ Choose an island to subscribe:*"
    )
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id, text=msg, reply_markup=reply_markup, parse_mode="MarkdownV2"
    )


async def subvessel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe user to a vessel by id or partial name. Shows inline options on multiple matches."""
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id

    # For groups/channels, ensure the chat itself exists as a user record
    if chat.type in ["group", "supergroup", "channel"]:
        try:
            create_user(
                telegram_id=chat_id,
                chat_type=chat.type,
                username=None,
                first_name=chat.title,
                last_name=None,
            )
        except Exception:
            pass
    # For private chats, use the actual user info
    elif user:
        try:
            create_user(
                telegram_id=chat_id,
                chat_type=chat.type,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )
        except Exception:
            pass

    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*⛴ Add a vessel*\n"
                "Use: */addvessel* \\<vessel name or id\\>\n"
                "Examples: */addvessel* Speed Star  \|  */addvessel* 123\n\n"
                "Tip: Try a keyword \\(e\\.g\\., ‘Star’\\) to see a list\\. 🔎"
            ),
            parse_mode="MarkdownV2",
        )
        return

    q = " ".join(context.args).strip()

    # Get user's current subscriptions
    subs = get_user_subscriptions(chat_id)
    subbed_vessels = {v.id: v for v in subs.get("vessels", [])}

    # if numeric, try id exact
    if q.isdigit():
        v = Vessel.get_or_none(Vessel.id == int(q))
        if not v:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"😕 No vessel found with id {esc_md(q)}\.",
                parse_mode="MarkdownV2",
            )
            return

        if v.id in subbed_vessels:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 You’re already subscribed to {esc_md(v.name)} \\({v.id}\\)\\.",
                parse_mode="MarkdownV2",
            )
            return

        sub, created, err = subscribe_user_to_vessel(chat_id, v.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Subscribed to {esc_md(v.name)} \\({v.id}\\)\\! I’ll keep you posted\\.",
                parse_mode="MarkdownV2",
            )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ You’ve reached the maximum of 10 vessel subscriptions\\. Use */unsub* to free a slot\\.",
                    parse_mode="MarkdownV2",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Failed to subscribe to this vessel\\. Please try again\\.",
                    parse_mode="MarkdownV2",
                )
        return

    # Get matches and split into already subscribed and available
    matches = list(Vessel.select().where(Vessel.name.contains(q)).limit(10))
    already_subbed = []
    available = []
    for v in matches:
        if v.id in subbed_vessels:
            already_subbed.append(v)
        else:
            available.append(v)

    if not matches:
        await context.bot.send_message(
            chat_id=chat_id, text=f"😕 No vessels found matching ‘{esc_md(q)}’\\. Try a shorter keyword\\.", parse_mode="MarkdownV2"
        )
        return

    # If only one match and already subscribed
    if len(matches) == 1 and matches[0].id in subbed_vessels:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔔 You’re already subscribed to {esc_md(matches[0].name)} \\({matches[0].id}\\)\\.",
            parse_mode="MarkdownV2",
        )
        return

    # If only one match and not subscribed
    if len(matches) == 1:
        v = matches[0]
        sub, created, err = subscribe_user_to_vessel(chat_id, v.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Subscribed to {esc_md(v.name)} \({v.id}\)\!",
                parse_mode="MarkdownV2",
            )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ You’ve reached the maximum of 10 vessel subscriptions\. Use */unsub* to remove one\.",
                    parse_mode="MarkdownV2",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, text="Failed to subscribe to vessel\.", parse_mode="MarkdownV2"
                )
        return

    # Show already subscribed vessels first
    msg_parts = []
    if already_subbed:
        msg_parts.append("*🔔 Already subscribed:*")
        for v in already_subbed:
            msg_parts.append(f"• {esc_md(v.name)} \({v.id}\)")

    # Then show keyboard for available ones
    keyboard = []
    for v in available:
        keyboard.append(
            [InlineKeyboardButton(f"{v.name}", callback_data=f"sub_vessel:{v.id}")]
        )

    if not keyboard:
        # All matches are already subscribed
        await context.bot.send_message(
            chat_id=chat_id, text="\n".join(msg_parts), parse_mode="MarkdownV2"
        )
        return

    msg = (
        "\n".join(msg_parts + ["", "*➕ Available vessels to subscribe:*"])
        if msg_parts
        else "*➕ Choose a vessel to subscribe:*"
    )
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text=msg,
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_id = chat.id
    subs = get_user_subscriptions(chat_id)
    port_list = subs.get("ports", [])
    vessel_list = subs.get("vessels", [])

    def esc(s):
        return escape_markdown(str(s), version=2)

    lines = ["*🧾 Your subscriptions*:\n"]
    if port_list:
        lines.append("*🏝 Ports:*")
        for p in port_list:
            lines.append(f"• {esc(p.name)}")
    else:
        lines.append("*🏝 Ports:* \- None")

    if vessel_list:
        lines.append("\n*⛴ Vessels:*")
        for v in vessel_list:
            lines.append(f"• {esc(v.name)}")
    else:
        lines.append("\n*⛴ Vessels:* \- None")

    await context.bot.send_message(
        chat_id=chat_id, text="\n".join(lines), parse_mode="MarkdownV2"
    )


async def unsub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's subscriptions with inline buttons to unsubscribe."""
    chat = update.effective_chat
    chat_id = chat.id
    subs = get_user_subscriptions(chat_id)
    port_list = subs.get("ports", [])
    vessel_list = subs.get("vessels", [])

    keyboard = []
    for p in port_list:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔕🏝 Unsubscribe {p.name}", callback_data=f"unsub_port:{p.id}"
                )
            ]
        )
    for v in vessel_list:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔕⛴ Unsubscribe {v.name}", callback_data=f"unsub_vessel:{v.id}"
                )
            ]
        )

    if not keyboard:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔎 No active subscriptions found\. Use */addisland* or */addvessel* to get started\!",
            parse_mode="MarkdownV2",
        )
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text="*🔕 Choose a subscription to remove:*",
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
    )


## findchannel removed per request

async def channelsubvessel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to subscribe a channel to a vessel.
    Usage: /channeladdvessel \<channel_username\> \<vessel_name\>"""
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/channeladdvessel \<channel_username\> \<vessel_name\>`\n"
                "*Example:*\n"
                "`/channeladdvessel @channel1 speedstar`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    try:
        channel_username = context.args[0].strip("@")  # Remove @ if present
        vessel_name = " ".join(context.args[1:]).strip()

        # Check if channel exists as a user
        channel = User.get_or_none(User.username == channel_username)
        if not channel:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"😕 Channel @{channel_username} not found. Please add it first using /addchannel",
            )
            return

        # Get matches and split into already subscribed and available
        matches = list(
            Vessel.select().where(Vessel.name.contains(vessel_name)).limit(10)
        )
        subs = get_user_subscriptions(channel.chat_id)
        subbed_vessels = {v.id: v for v in subs.get("vessels", [])}

        if not matches:
            await context.bot.send_message(
                chat_id=chat_id, text=f"😕 No vessels found matching '{vessel_name}'."
            )
            return

        # If only one match and already subscribed
        if len(matches) == 1 and matches[0].id in subbed_vessels:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 Channel @{channel_username} is already subscribed to {matches[0].name} ({matches[0].id}).",
            )
            return

        # If only one match and not subscribed
        if len(matches) == 1:
            v = matches[0]
            sub, created, err = subscribe_user_to_vessel(channel.chat_id, v.id)
            if sub:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Channel @{channel_username} subscribed to vessel {v.name} ({v.id}).",
                )
            else:
                if err == "limit_reached":
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ Channel has reached the maximum of 10 vessel subscriptions.",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id, text="❌ Failed to subscribe channel to vessel."
                    )
            return

        # Show keyboard for multiple matches
        keyboard = []
        for v in matches:
            if v.id not in subbed_vessels:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"{v.name}",
                            callback_data=f"channel_sub_vessel:{channel.chat_id}:{v.id}",
                        )
                    ]
                )

        if not keyboard:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 Channel @{channel_username} is already subscribed to all matching vessels.",
            )
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"➕ Choose a vessel to subscribe channel @{channel_username} to:",
            reply_markup=reply_markup,
        )

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❗️ Invalid channel username format",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {str(e)}")


async def listchannels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all available channels. Optionally filter by @username or island name."""
    chat = update.effective_chat
    chat_id = chat.id

    try:
        # Optional filter: by island name or @username
        q = " ".join(context.args).strip() if getattr(context, "args", None) else ""

        # Base query: all channel users with optional left join to main port
        base = (
            User.select(User, Port)
            .join(Port, JOIN.LEFT_OUTER, on=(User.main_port == Port.id))
            .where((User.chat_type == "channel") & (User.username.is_null(False)))
        )

        if q:
            if q.startswith("@"):
                uq = q.lstrip("@")
                base = base.where(User.username.contains(uq))
                channel_users = base.order_by(User.username.asc(nulls="LAST"))
            else:
                # Search by island name if available
                base = base.where(Port.name.contains(q))
                channel_users = base.order_by(Port.name.asc(), User.username.asc(nulls="LAST"))
        else:
            # Default: list ALL channels alphabetically by username
            channel_users = base.order_by(User.username.asc(nulls="LAST"))

        if not channel_users:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    (
                        f"📣 Channels matching {q}\n\n" if q else "📣 Available channels\n\n"
                    )
                    + ("🔎 No channels available yet." if not q else "🔎 No channels match your search.")
                ),
                disable_web_page_preview=True,
            )
            return

        if q:
            header = (
                f"📣 Channels matching @{q.lstrip('@')}\n"
                if q.startswith("@")
                else f"📣 Channels for islands matching {q}\n"
            )
        else:
            header = "📣 Available channels\n"

        lines = [header]
        for cu in channel_users:
            port_name = cu.main_port.name if cu.main_port else "Unknown"
            username = cu.username or ""
            username_display = username.lstrip("@")
            # Show channel list primarily; include island name if available
            suffix = f" – {port_name}" if cu.main_port else ""
            lines.append(f"• @{username_display}{suffix}")

        text = "\n".join(lines)
        # Do NOT set Markdown parse mode to keep @mentions clickable across all characters
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
        )
    except Exception as e:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Error fetching channels: {str(e)}",
        )

async def channelsubisland(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to subscribe a channel to a port/island.
    Usage: /channeladdisland \<channel_username\> \<port_name\>"""
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/channeladdisland \<channel_username\> \<port_name\>`\n"
                "*Example:*\n"
                "`/channeladdisland @channel1 Male`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    try:
        channel_username = context.args[0].strip("@")  # Remove @ if present
        port_name = " ".join(context.args[1:]).strip()

        # Check if channel exists as a user
        channel = User.get_or_none(User.username == channel_username)
        if not channel:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"😕 Channel @{channel_username} not found. Please add it first using /addchannel",
            )
            return

        # Get all matching ports and channel's current subscriptions
        matches = list(Port.select().where(Port.name.contains(port_name)).limit(10))
        subs = get_user_subscriptions(channel.chat_id)
        subbed_ports = {p.id: p for p in subs.get("ports", [])}

        if not matches:
            await context.bot.send_message(
                chat_id=chat_id, text=f"😕 No islands found matching '{port_name}'."
            )
            return

        # If only one match and already subscribed
        if len(matches) == 1 and matches[0].id in subbed_ports:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Channel @{channel_username} is already subscribed to {matches[0].name}.",
            )
            return

        # If only one match and not subscribed
        if len(matches) == 1:
            port = matches[0]
            sub, created, err = subscribe_user_to_port(channel.chat_id, port.id)
            if sub:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Channel @{channel_username} subscribed to {port.name}.",
                )
            else:
                if err == "limit_reached":
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ Channel has reached the maximum of 10 island subscriptions.",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Failed to subscribe channel to {port.name}.",
                    )
            return

        # Show keyboard for multiple matches
        keyboard = []
        for p in matches:
            if p.id not in subbed_ports:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            p.name,
                            callback_data=f"channel_sub_port:{channel.chat_id}:{p.id}",
                        )
                    ]
                )

        if not keyboard:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 Channel @{channel_username} is already subscribed to all matching islands.",
            )
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"➕ Choose an island to subscribe channel @{channel_username} to:",
            reply_markup=reply_markup,
        )

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❗️ Invalid channel username format",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {str(e)}")


async def addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a channel as a user and set its main port. Admin only command.
    Usage: /addchannel port_name channel_id channel_username"""
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="⛔️ This command can only be used by admin"
        )
        return

    # Check if correct number of arguments provided
    if len(context.args) != 3:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*Usage:*\n"
                "`/addchannel \<port_name\> \<channel_id\> \<channel_username\>`\n"
                "*Example:*\n"
                "`/addchannel Male 10012345674490 @male_port`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    port_name, channel_id, channel_username = context.args

    try:
        # Convert channel_id to integer
        channel_id = int(channel_id)

        # Find matching ports
        matches = list(Port.select().where(Port.name.contains(port_name)))

        if not matches:
            await context.bot.send_message(
                chat_id=chat_id, text=f"😕 No islands found matching '{port_name}'"
            )
            return

        if len(matches) == 1:
            port = matches[0]
        else:
            # Show keyboard for multiple matches
            keyboard = []
            for p in matches:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            p.name,
                            callback_data=f"add_channel:{channel_id}:{channel_username}:{p.id}",
                        )
                    ]
                )

            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🔎 Multiple islands found matching '{port_name}'. Please select one:",
                reply_markup=reply_markup,
            )
            return

        # If a channel already exists for this port, update it; otherwise create/assign
        existing_channel = port.channel
        if existing_channel:
            if existing_channel.chat_id == channel_id:
                # Same channel record: update metadata
                existing_channel.chat_type = "channel"
                existing_channel.username = channel_username
                existing_channel.first_name = port_name
                existing_channel.main_port = port
                existing_channel.save()
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Updated channel {channel_username} for island {port_name}",
                )
            else:
                # Reassign to new channel_id: detach old, attach/update new
                try:
                    new_user, _ = User.get_or_create(chat_id=channel_id)
                except Exception:
                    # Fallback if get_or_create fails due to type or pk issues
                    new_user = User.create(
                        chat_id=channel_id,
                        chat_type="channel",
                        username=channel_username,
                        first_name=port_name,
                        last_name=None,
                    )
                # Detach old channel from this port to keep uniqueness
                existing_channel.main_port = None
                existing_channel.save()

                # Update/attach new channel
                new_user.chat_type = "channel"
                new_user.username = channel_username
                new_user.first_name = port_name
                new_user.main_port = port
                new_user.save()

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Reassigned island {port_name} to channel {channel_username}",
                )
        else:
            # No channel yet for this port: create or update provided channel user
            user, created = User.get_or_create(
                chat_id=channel_id,
                defaults={
                    "chat_type": "channel",
                    "username": channel_username,
                    "first_name": port_name,
                    "main_port": port,
                },
            )

            if not created:
                user.chat_type = "channel"
                user.username = channel_username
                user.first_name = port_name
                user.main_port = port
                user.save()

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Successfully {'added' if created else 'updated'} channel {channel_username} for island {port_name}",
            )

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❗️ Invalid channel ID format. Please provide a valid integer ID",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error: {str(e)}")


# stats
async def island_stats(
    update: Update = None, context: ContextTypes.DEFAULT_TYPE = None
):
    def esc(val):
        return escape_markdown(str(val), version=2)

    # Handle both scheduled and command usage
    chat_id = update.effective_chat.id if update else context._chat_id

    # If no arguments provided, show usage message
    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "*📊 Island stats*\n"
                "Use: */islandstats* \<island name\>\n"
                "Example: */islandstats* Male"
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
            chat_id=chat_id, text=f"😕 No islands found matching ‘{esc_md(port_name)}’\.", parse_mode="MarkdownV2"
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
            text=f"🔎 Multiple islands found matching ‘{esc_md(port_name)}’\. Please select one:",
            reply_markup=reply_markup,
            parse_mode="MarkdownV2",
        )
        return

    # Single match found, get stats directly
    port = matches[0]
    await send_port_stats(context, chat_id, port.id)


async def send_port_stats(context, chat_id, port_id):
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
        + f"\n_\\#dailyreport_ _\\#{date.replace(' ', '')}_ _\\#{re.sub(r'[^0-9a-zA-Z]+', '', port_name)}_"
    )

    formatted_response = f"{highlights}\n{vessel_rankings}{peak_hours}{daily_totals}"
    print(formatted_response, flush=True)
    await context.bot.send_message(
        chat_id=chat_id,
        text=formatted_response,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


async def vessel_stats(
    update: Update = None, context: ContextTypes.DEFAULT_TYPE = None
):

    response = "⏳ Coming soon، إن شاء الله"
    await context.bot.send_message(
        chat_id=context._chat_id,
        text=response,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cq = update.callback_query
    if not cq or not cq.data:
        return
    await cq.answer()
    data = cq.data
    # The user who clicked
    chat = cq.message.chat
    chat_id = chat.id
    chat_type = chat.type

    # For inline button clicks, always use the chat where the button was clicked
    # regardless of who clicked it
    try:
        if chat_type in ["group", "supergroup", "channel"]:
            create_user(
                telegram_id=chat_id,
                chat_type=chat_type,
                username=None,
                first_name=chat.title,
                last_name=None,
            )
        else:
            # Private chat
            click_user = cq.from_user
            create_user(
                telegram_id=chat_id,
                chat_type=chat_type,
                username=(click_user.username if click_user else None),
                first_name=(click_user.first_name if click_user else ""),
                last_name=(click_user.last_name if click_user else None),
            )
    except Exception:
        pass

    click_id = chat_id  # Use the chat ID consistently for subscriptions

    if data.startswith("sub_port:"):
        try:
            pid = int(data.split(":", 1)[1])
            sub, created, err = subscribe_user_to_port(click_id, pid)
            if sub:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(text=f"Subscribed to {port.name}.")
                except Exception:
                    await cq.edit_message_text(text=f"Subscribed to port.")
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="You have reached the maximum of 10 port subscriptions."
                    )
                else:
                    try:
                        port = Port.get_by_id(pid)
                        await cq.edit_message_text(text=f"Failed to subscribe to {port.name}.")
                    except Exception:
                        await cq.edit_message_text(text=f"Failed to subscribe to port.")
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("sub_vessel:"):
        try:
            vid = int(data.split(":", 1)[1])
            sub, created, err = subscribe_user_to_vessel(click_id, vid)
            if sub:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(text=f"Subscribed to {v.name}.")
                except Exception:
                    await cq.edit_message_text(text=f"Subscribed to vessel.")
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="You have reached the maximum of 10 vessel subscriptions."
                    )
                else:
                    try:
                        v = Vessel.get_by_id(vid)
                        await cq.edit_message_text(text=f"Failed to subscribe to {v.name}.")
                    except Exception:
                        await cq.edit_message_text(text=f"Failed to subscribe to vessel.")
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("unsub_port:"):
        try:
            pid = int(data.split(":", 1)[1])
            ok = unsubscribe_user_from_port(click_id, pid)
            if ok:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(text=f"Unsubscribed from {port.name}.")
                except Exception:
                    await cq.edit_message_text(text=f"Unsubscribed from port.")
            else:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(text=f"Failed to unsubscribe from {port.name}.")
                except Exception:
                    await cq.edit_message_text(text=f"Failed to unsubscribe from port.")
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("unsub_vessel:"):
        try:
            vid = int(data.split(":", 1)[1])
            ok = unsubscribe_user_from_vessel(click_id, vid)
            if ok:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(text=f"Unsubscribed from {v.name}.")
                except Exception:
                    await cq.edit_message_text(text=f"Unsubscribed from vessel.")
            else:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(text=f"Failed to unsubscribe from {v.name}.")
                except Exception:
                    await cq.edit_message_text(text=f"Failed to unsubscribe from vessel.")
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("add_channel:"):
        try:
            _, channel_id, channel_username, port_id = data.split(":")
            channel_id = int(channel_id)
            port_id = int(port_id)

            try:
                port = Port.get_by_id(port_id)
                existing_channel = port.channel
                if existing_channel:
                    if existing_channel.chat_id == channel_id:
                        existing_channel.chat_type = "channel"
                        existing_channel.username = channel_username
                        existing_channel.first_name = port.name
                        existing_channel.main_port = port
                        existing_channel.save()
                        await cq.edit_message_text(
                            text=f"✅ Updated channel {channel_username} for island {port.name}"
                        )
                    else:
                        # Reassign: detach old, attach/update new user
                        try:
                            new_user, _ = User.get_or_create(chat_id=channel_id)
                        except Exception:
                            new_user = User.create(
                                chat_id=channel_id,
                                chat_type="channel",
                                username=channel_username,
                                first_name=port.name,
                                last_name=None,
                            )
                        existing_channel.main_port = None
                        existing_channel.save()

                        new_user.chat_type = "channel"
                        new_user.username = channel_username
                        new_user.first_name = port.name
                        new_user.main_port = port
                        new_user.save()

                        await cq.edit_message_text(
                            text=f"✅ Reassigned island {port.name} to channel {channel_username}"
                        )
                else:
                    user, created = User.get_or_create(
                        chat_id=channel_id,
                        defaults={
                            "chat_type": "channel",
                            "username": channel_username,
                            "first_name": port.name,
                            "main_port": port,
                        },
                    )

                    if not created:
                        user.chat_type = "channel"
                        user.username = channel_username
                        user.first_name = port.name
                        user.main_port = port
                        user.save()

                    await cq.edit_message_text(
                        text=f"✅ Successfully {'added' if created else 'updated'} channel {channel_username} for island {port.name}"
                    )
            except Port.DoesNotExist:
                await cq.edit_message_text(text=f"Error: Port (id={port_id}) not found")
            except Exception as e:
                await cq.edit_message_text(text=f"Error: {str(e)}")
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("set_main:"):
        try:
            pid = int(data.split(":", 1)[1])
            ok = set_main_port(click_id, pid)
            if ok:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(text=f"Main port set to {port.name}.")
                except Exception:
                    await cq.edit_message_text(text=f"Main port set.")
            else:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(text=f"Failed to set main port to {port.name}.")
                except Exception:
                    await cq.edit_message_text(text=f"Failed to set main port.")
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("channel_sub_vessel:"):
        try:
            _, channel_id, vid = data.split(":")
            channel_id = int(channel_id)
            vid = int(vid)

            # Only admin can use these callbacks
            if int(chat_id) != int(ADMIN_CHAT_ID):
                await cq.edit_message_text(text="Only admin can use this function.")
                return

            sub, created, err = subscribe_user_to_vessel(channel_id, vid)
            if sub:
                try:
                    v = Vessel.get_by_id(vid)
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) subscribed to {v.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) subscribed to vessel."
                    )
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="Channel has reached the maximum of 10 vessel subscriptions."
                    )
                else:
                    try:
                        v = Vessel.get_by_id(vid)
                        await cq.edit_message_text(
                            text=f"Failed to subscribe channel to {v.name}."
                        )
                    except Exception:
                        await cq.edit_message_text(
                            text=f"Failed to subscribe channel to vessel."
                        )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("channel_sub_port:"):
        try:
            _, channel_id, pid = data.split(":")
            channel_id = int(channel_id)
            pid = int(pid)

            # Only admin can use these callbacks
            if int(chat_id) != int(ADMIN_CHAT_ID):
                await cq.edit_message_text(text="Only admin can use this function.")
                return

            sub, created, err = subscribe_user_to_port(channel_id, pid)
            if sub:
                try:
                    port = Port.get_by_id(pid)
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) subscribed to {port.name}."
                    )
                except Exception:
                    await cq.edit_message_text(
                        text=f"Channel (id={channel_id}) subscribed to port."
                    )
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="Channel has reached the maximum of 10 port subscriptions."
                    )
                else:
                    try:
                        port = Port.get_by_id(pid)
                        await cq.edit_message_text(
                            text=f"Failed to subscribe channel to {port.name}."
                        )
                    except Exception:
                        await cq.edit_message_text(
                            text=f"Failed to subscribe channel to port."
                        )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    # get_port_channel callback removed with /findchannel

    elif data.startswith("get_port_stats:"):
        try:
            port_id = int(data.split(":", 1)[1])
            # Delete the selection message
            await cq.message.delete()
            # Send stats in a new message
            await send_port_stats(context, chat_id, port_id)
        except Exception as e:
            await cq.edit_message_text(text=f"Error retrieving stats: {str(e)}")
