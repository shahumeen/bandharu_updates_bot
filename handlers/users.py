from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from peewee import JOIN

from .common import esc_md
from model_helpers import (
    Port,
    Vessel,
    User,
    create_user,
    subscribe_user_to_port,
    subscribe_user_to_vessel,
    get_user_subscriptions,
)


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
        (
            "*👋 Welcome to Bandharu Updates Bot*\n\n"
            "Stay notified about islands and vessels you care about\\."
        )
        + "\n\n"
        + (
            "🧭 *Quick commands:*\n"
            "• */addisland* \\<name\\> \\- Subscribe to an island/port 🏝\n"
            "• */addvessel* \\<name or id\\> \\- Subscribe to a vessel ⛴\n"
            "• */settings* \\- View your subscriptions ⚙️\n"
            "• */unsub* \\- Manage and remove subscriptions 🔕\n"
            "• */islandstats* \\<island\\> \\- Today’s stats 📊\n"
            "• */vesselstats* \\<vessel\\> \\- Vessel stats \\(beta\\) 🧪\n\n"
            f"Island update channels: [BandharuUpdates](t.me/addlist/ziV1Htn9OR9iNWI1)"
        )
        + "\n"
        + ("👾 Uses FollowMe\\.mv API")
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
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
            text=f"🔔 You’re already subscribed to {esc_md(matches[0].name)}\\.",
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
                "Examples: */addvessel* Speed Star  |  */addvessel* 123\n\n"
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
                text=f"😕 No vessel found with id {esc_md(q)}\\.",
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
            chat_id=chat_id,
            text=f"😕 No vessels found matching ‘{esc_md(q)}’\\. Try a shorter keyword\\.",
            parse_mode="MarkdownV2",
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
                    chat_id=chat_id,
                    text="Failed to subscribe to vessel\.",
                    parse_mode="MarkdownV2",
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

    from telegram.helpers import escape_markdown

    def esc(s):
        return escape_markdown(str(s), version=2)

    lines = ["*🧾 Your subscriptions*:\n"]
    if port_list:
        lines.append("*🏝 Ports:*")
        for p in port_list:
            lines.append(f"• {esc(p.name)}")
    else:
        lines.append("*🏝 Ports:* \\- None")

    if vessel_list:
        lines.append("\n*⛴ Vessels:*")
        for v in vessel_list:
            lines.append(f"• {esc(v.name)}")
    else:
        lines.append("\n*⛴ Vessels:* \\- None")

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

    from telegram.helpers import escape_markdown

    keyboard = []
    for p in port_list:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔕Unsubscribe: 📍{p.name}", callback_data=f"unsub_port:{p.id}"
                )
            ]
        )
    for v in vessel_list:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔕Unsubscribe: ⛴{v.name}", callback_data=f"unsub_vessel:{v.id}"
                )
            ]
        )

    if not keyboard:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔎 No active subscriptions found\\. Use */addisland* or */addvessel* to get started\\!",
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


async def toggledepartures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle departure notifications for the current chat/user."""
    chat = update.effective_chat
    user_info = update.effective_user
    chat_id = chat.id

    # Ensure user record exists
    user = User.get_or_none(User.chat_id == chat_id)
    if not user:
        try:
            if chat.type in ["group", "supergroup", "channel"]:
                create_user(
                    telegram_id=chat_id,
                    chat_type=chat.type,
                    username=None,
                    first_name=chat.title or "",
                    last_name=None,
                )
            else:
                create_user(
                    telegram_id=chat_id,
                    chat_type=chat.type,
                    username=(user_info.username if user_info else None),
                    first_name=(user_info.first_name if user_info else ""),
                    last_name=(user_info.last_name if user_info else None),
                )
            user = User.get_or_none(User.chat_id == chat_id)
        except Exception:
            user = None

    if not user:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Could not access your settings right now. Please try again.",
        )
        return

    # Toggle flag
    new_value = not bool(user.notify_on_departure)
    user.notify_on_departure = new_value
    try:
        user.save()
    except Exception:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Failed to update your settings. Please try again later.",
        )
        return

    status_text = "ON" if new_value else "OFF"
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🚦 Departure notifications are now {status_text} for this chat.",
    )


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
                channel_users = base.order_by(
                    Port.name.asc(), User.username.asc(nulls="LAST")
                )
        else:
            # Default: list ALL channels alphabetically by username
            channel_users = base.order_by(User.username.asc(nulls="LAST"))

        if not channel_users:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    (
                        f"📣 Channels matching {q}\n\n"
                        if q
                        else "📣 Available channels\n\n"
                    )
                    + (
                        "🔎 No channels available yet."
                        if not q
                        else "🔎 No channels match your search."
                    )
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
