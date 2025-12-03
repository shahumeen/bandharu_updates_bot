from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.error import Forbidden, BadRequest
from telegram.ext import ContextTypes, ConversationHandler

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


MAP_QUERY = "https://www.google.com/maps?q="
VESSEL_QUERY = "https://m.followme.mv/public/?pg=info&id="

# Conversation states
AWAITING_ISLAND_NAME = 1
AWAITING_VESSEL_NAME = 2
AWAITING_ISLAND_STATS = 3
AWAITING_VESSEL_STATS = 4


def send_main_menu(update: Update = None, context: ContextTypes.DEFAULT_TYPE = None, chat_id: int = None):
    """Send main menu with reply keyboard buttons."""
    keyboard = [
        [KeyboardButton("🏝 Add Island"), KeyboardButton("⛴ Add Vessel")],
        [KeyboardButton("⚙️ Settings"), KeyboardButton("🗑️ Unsubscribe")],
        [KeyboardButton("🚦 Toggle Departures")],
        [KeyboardButton("📈 Island Stats"), KeyboardButton("📊 Vessel Stats")],
        [KeyboardButton("📣 Island Channels"), KeyboardButton("❓ Help")],
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    if chat_id is None and update:
        chat_id = update.effective_chat.id
    
    return context.bot.send_message(
        chat_id=chat_id,
        text="📱 *Main Menu*\n\nChoose an action:",
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
    )


def get_back_to_menu_keyboard():
    """Get inline keyboard with back to menu button."""
    keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]]
    return InlineKeyboardMarkup(keyboard)



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start: create user (if needed) and send formatted introduction."""
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id

    # Ensure user record exists
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

    # Compute total number of private users to show usage stats
    try:
        total_private = User.select().where(User.chat_type == "private").count()
    except Exception:
        total_private = None

    people_line = (
        f"\n📊 _User Count: *{total_private}*_\n" if total_private is not None else ""
    )

    welcome_message = fr"""
🏝️ Welcome to Bandharu Updates Bot\!
━━━━━━━━━━━━━━━━━━━━━━━

_Your friendly vessel tracking assistant for the Maldives_ 🌊

✨ *How It Works:*
*1* • Subscribe to islands 🏝️ and vessels ⛴️
*2* • Get instant alerts when they match
*3* • Stay updated with arrivals \& departures

━━━━━━━━━━━━━━━━━━━━━━━

⚡ *Quick Start Guide:*

🎯 _*Add Subscriptions:*_
• /addport \- _Subscribe to an island or port 🏝️_
• /addvessel \- _Subscribe to a vessel ⛴️_

⚙️ _*Manage Settings:*_
• /settings \- _View your subscriptions 🔍_
• /unsub \- _Remove subscriptions 🗑️_
• /toggledepartures \- _Toggle departure notifications 🚦_

📊 _*Get Statistics:*_
• /islandstats \- _Island statistics 📈_
• /vesselstats \- _Vessel statistics \(beta\) 🧪_

━━━━━━━━━━━━━━━━━━━━━━━

📣 *Island\-Wide Updates:*

Want _*all activity*_ for specific islands\?  
Join our dedicated [Bandharu update channels](https://telegra.ph/Island-update-Channels-11-08)

_Can't find your island's channel\?_  
Ask @BUBSupport to add it\! 💬

━━━━━━━━━━━━━━━━━━━━━━━
{people_line}
🧑‍💻 _Are you a developer? contribute on [GitHub](https://github.com/shahumeen/bandharu_updates_bot)_

👾 _Uses FollowMe\.mv API_

`</> Made with ❤️ by` @shahumeen
"""
    # Send and attempt to pin the branding image every /start
    try:
        sent_photo = await context.bot.send_photo(
            chat_id=chat_id,
            photo="https://followme.mv/api/images/icon_50.png",
            caption="FollowMe",
        )
        # Prefer checking permissions before attempting to pin in groups
        try:
            can_pin = True
            if chat.type in ["group", "supergroup"]:
                # Check the bot's permissions in this chat
                me = await context.bot.get_chat_member(chat_id, context.bot.id)
                status = getattr(me, "status", None)
                can_pin = status in ("administrator", "creator")
                # If administrator, ensure the specific permission is granted
                if can_pin and hasattr(me, "can_pin_messages"):
                    can_pin = bool(getattr(me, "can_pin_messages", False))

            if can_pin:
                await context.bot.pin_chat_message(
                    chat_id=chat_id,
                    message_id=sent_photo.message_id,
                    disable_notification=True,
                )
            else:
                # Gently inform in groups if we cannot pin
                if chat.type in ["group", "supergroup"]:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            "I don't have permission to pin messages here. "
                            "Please pin the above image to abide by FollowMe.mv API rules."
                        ),
                    )
        except (Forbidden, BadRequest):
            # Lacking rights or other pin restrictions; continue without failing
            pass
        except Exception:
            # Any other unexpected error; ignore to avoid breaking /start
            pass
    except Exception:
        # If image fetch fails, continue with text
        pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=welcome_message,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )
    
    # Send main menu
    await send_main_menu(update, context, chat_id)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show a friendly help with commands and examples."""
    chat_id = update.effective_chat.id

    help_message = r"""
❓🌊 *Help & Commands Guide*

_Track Maldives vessel movements in real\-time and get notified when your subscribed vessels reach your favorite islands\!_

*How I Work:* 🤖
I monitor vessel movements and notify you when your subscribed ⛴ _*vessels*_ visit your subscribed 🏝 _*islands*_\.

_*You need at least ONE island and ONE vessel to start receiving alerts*_

━━━━━━━━━━━━━━━━━━━━━━━
🎯 *How It Works:*
• Subscribe to islands \& vessels
• Get instant alerts when they match
• Receive arrival \& departure notifications

━━━━━━━━━━━━━━━━━━━━━━━
⚡ *Quick Commands:*

🏝️ *Island Actions:*
• /addport \- _Subscribe to an island or port_
• /islandstats \- _Get island statistics_

⛴️ *Vessel Actions:*
• /addvessel \- _Subscribe to a vessel_
• /vesselstats \- _Vessel statistics \(beta\)_

⚙️ *Manage Settings:*
• /settings \- _View your subscriptions_
• /unsub \- _Remove subscriptions_
• /toggledepartures \- _Toggle departure alerts_

📱 *General:*
• /start \- _Welcome overview_
• /help \- _This help menu_
• /islandchannels \- _Island update channels_

💡 *Usage Tips*

*• Subscription Limits:*  
   You can subscribe to _*20 islands*_ and _*20 vessels*_

*• Matching Logic:*  
   We notify when _*any*_ of your vessels visit _*any*_ of your islands _*or*_ for all island your vessels visit if you _*don't have*_ an island subscription\.

*• Departure Alerts:*  
   Use /toggledepartures to control departure notifications

━━━━━━━━━━━━━━━━━━━━━━━
📣 *Island Channels*

Want _*all activity*_ for specific islands\?  
Join our dedicated [Bandharu update channels](https://telegra.ph/Island-update-Channels-11-08)

• Browse: /islandchannels  

_Can't find your island's channel\?_  
Ask @BUBSupport to add it\! 💬

━━━━━━━━━━━━━━━━━━━━━━━
🎯*Need More Help?*

contact @BUBSupport for assistance 🤝
"""

    await context.bot.send_message(
        chat_id=chat_id,
        text=help_message,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


async def unrecognized_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle any messages that are not commands."""
    # Ignore non-text or service messages (e.g., pin events)
    if not update.message or not update.message.text:
        return
    await update.message.reply_text(
        "🤖 I couldn’t recognize that\\. Try /help for commands\\.",
        parse_mode="MarkdownV2",
    )


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown /commands that are not registered."""
    if not update.message or not update.message.text:
        return
    cmd = update.message.text.split()[0]
    # Escape markdown special chars
    from telegram.helpers import escape_markdown

    esc_cmd = escape_markdown(cmd, version=2)
    await update.message.reply_text(
        f"❓ Unknown command. Use /help to see available commands.",
        disable_web_page_preview=True,
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
                "*Usage:*\n"
                "`/addport <island_name>`\n"
                "*Example:*\n"
                "`/addport Male`"
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
            text=f"😕 No islands found matching ‘{esc_md(name)}’\\. Try a shorter keyword\\.",
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
            text=f"🔔 You’re already subscribed to _*[{esc_md(matches[0].name)}]({MAP_QUERY}{matches[0].name})*_",
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        return

    # If only one match and not subscribed
    if len(matches) == 1:
        port = matches[0]
        sub, created, err = subscribe_user_to_port(chat_id, port.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Subscribed to _*[{esc_md(port.name)}]({MAP_QUERY}{port.name})*_",
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            if not subs.get("vessels"):
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "⚠️ To receive notifications you also need at least *ONE* vessel subscription\\. Use /addvessel to add one\\."
                    ),
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ You’ve reached the maximum of *20* island subscriptions\\. Remove one with /unsub to add more\\.",
                    parse_mode="MarkdownV2",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Failed to subscribe to _*{esc_md(port.name)}*_\\. Please try again shortly\\.",
                    parse_mode="MarkdownV2",
                )
        return

    # Show already subscribed ports first
    msg_parts = []
    if already_subbed:
        msg_parts.append("*🔔 Already subscribed:*\n")
        for p in already_subbed:
            msg_parts.append(f"• _*[{esc_md(p.name)}]({MAP_QUERY}{p.name})*_")

    # Then show keyboard for available ones
    keyboard = []
    for p in available:
        keyboard.append(
            [InlineKeyboardButton(p.name, callback_data=f"sub_port:{p.id}")]
        )

    if not keyboard:
        # All matches are already subscribed
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(msg_parts),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        return

    msg = (
        "\n".join(msg_parts + ["", "*➕ Available islands to subscribe:*"])
        if msg_parts
        else "*➕ Choose an island to subscribe:*"
    )
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text=msg,
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
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
                "*Usage:*\n"
                "`/addvessel <vessel_name>`\n"
                "*Example:*\n"
                "`/addvessel RTL 101`"
            ),
            parse_mode="MarkdownV2",
        )
        return

    q = " ".join(context.args).strip()

    # Get user's current subscriptions
    subs = get_user_subscriptions(chat_id)
    subbed_vessels = {v.id: v for v in subs.get("vessels", [])}

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
            text=f"🔔 You’re already subscribed to _*[{esc_md(matches[0].name)}]({VESSEL_QUERY}{matches[0].id})*_",
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        return

    # If only one match and not subscribed
    if len(matches) == 1:
        v = matches[0]
        sub, created, err = subscribe_user_to_vessel(chat_id, v.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Subscribed to _*[{esc_md(v.name)}]({VESSEL_QUERY}{v.id})*_",
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ You’ve reached the maximum of *20* vessel subscriptions\\. Use /unsub to remove one\\.",
                    parse_mode="MarkdownV2",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Failed to subscribe to vessel\\.",
                    parse_mode="MarkdownV2",
                )
        return

    # Show already subscribed vessels first
    msg_parts = []
    if already_subbed:
        msg_parts.append("*🔔 Already subscribed:*")
        for v in already_subbed:
            msg_parts.append(f"• _*[{esc_md(v.name)}]({VESSEL_QUERY}{v.id})*_")

    # Then show keyboard for available ones
    keyboard = []
    for v in available:
        keyboard.append(
            [InlineKeyboardButton(f"{v.name}", callback_data=f"sub_vessel:{v.id}")]
        )

    if not keyboard:
        # All matches are already subscribed
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(msg_parts),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
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
        disable_web_page_preview=True,
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

    # Departure notification status
    user = User.get_or_none(User.chat_id == chat_id)
    dep_status = "ON 🔔" if (user and user.notify_on_departure) else "OFF 🔕"

    lines = ["*🧾 Your subscriptions*:\n"]
    lines.append(f"🚦 Departure notifications: _*{dep_status}*_")
    lines.append("")
    if port_list:
        lines.append("*🏝 Ports:*")
        for p in port_list:
            lines.append(f"• _*[{esc(p.name)}]({MAP_QUERY}{p.name})*_")
    else:
        lines.append("*🏝 Ports:* \\- None")

    if vessel_list:
        lines.append("\n*⛴ Vessels:*")
        for v in vessel_list:
            lines.append(f"• _*[{esc(v.name)}]({VESSEL_QUERY}{v.id})*_")
    else:
        lines.append("\n*⛴ Vessels:* \\- None")

    # Hint: if user has island subscriptions but no vessel subscriptions
    if port_list and not vessel_list:
        lines.append(
            "\n━━━━━━━━━━━━━━━━━━━━━━━\n\n⚠️ To receive notifications you also need at least *ONE* vessel subscription\\. Use /addvessel to add one\\."
        ),

    await context.bot.send_message(
        chat_id=chat_id,
        text="\n".join(lines),
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
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
                    f"Unsubscribe: {p.name} 📍", callback_data=f"unsub_port:{p.id}"
                )
            ]
        )
    for v in vessel_list:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"Unsubscribe: {v.name} ⛴", callback_data=f"unsub_vessel:{v.id}"
                )
            ]
        )

    if not keyboard:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🔎 No active subscriptions found\\. Use /addport or /addvessel to get started\\!\n\n"
            ),
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
    new_value = not user.notify_on_departure
    user.notify_on_departure = new_value
    try:
        user.save()
    except Exception:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Failed to update your settings. Please try again later.",
        )
        return

    reply = (
        "🔔 Departure notifications are now _*ON*_ for this chat\\."
        if new_value
        else "🔕 Departure notifications are now _*OFF*_ for this chat\\."
    )
    await context.bot.send_message(chat_id=chat_id, text=reply, parse_mode="MarkdownV2")


async def islandchannels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Share the curated Telegram list of island update channels."""
    chat = update.effective_chat
    chat_id = chat.id

    text = r"""📣 *Island Channels*

Want _*all activity*_ for specific islands\?  
Join our dedicated [Bandharu update channels](https://telegra.ph/Island-update-Channels-11-08)

_Can't find your island's channel\?_  
Ask @BUBSupport to add it\! 💬"""
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command - show main menu."""
    await send_main_menu(update, context)


# Button handlers that trigger conversation states
async def button_add_island(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Add Island' button press - ask for island name."""
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text="🏝 *Add Island Subscription*\n\nPlease enter the island name:",
        parse_mode="MarkdownV2",
    )
    return AWAITING_ISLAND_NAME


async def button_add_vessel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Add Vessel' button press - ask for vessel name."""
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text="⛴ *Add Vessel Subscription*\n\nPlease enter the vessel name or ID:",
        parse_mode="MarkdownV2",
    )
    return AWAITING_VESSEL_NAME


async def button_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Settings' button press."""
    await settings(update, context)
    return ConversationHandler.END


async def button_unsub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Unsubscribe' button press."""
    await unsub(update, context)
    return ConversationHandler.END


async def button_toggle_departures(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Toggle Departures' button press."""
    await toggledepartures(update, context)
    return ConversationHandler.END


async def button_island_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Island Stats' button press - ask for island name."""
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text="📈 *Island Statistics*\n\nPlease enter the island name:",
        parse_mode="MarkdownV2",
    )
    return AWAITING_ISLAND_STATS


async def button_vessel_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Vessel Stats' button press - ask for vessel name."""
    chat_id = update.effective_chat.id
    await context.bot.send_message(
        chat_id=chat_id,
        text="📊 *Vessel Statistics*\n\nPlease enter the vessel name or ID:",
        parse_mode="MarkdownV2",
    )
    return AWAITING_VESSEL_STATS


async def button_island_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Island Channels' button press."""
    await islandchannels(update, context)
    return ConversationHandler.END


async def button_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'Help' button press."""
    await help_command(update, context)
    return ConversationHandler.END


# Text input handlers for conversation states
async def handle_island_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle island name input after 'Add Island' button."""
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id
    
    # Create user if needed
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
    
    name = update.message.text.strip()
    
    # Get all matching ports and user's current subscriptions
    matches = list(Port.select().where(Port.name.contains(name)).limit(10))
    subs = get_user_subscriptions(chat_id)
    subbed_ports = {p.id: p for p in subs.get("ports", [])}
    
    if not matches:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"😕 No islands found matching '{esc_md(name)}'\\. Try a shorter keyword\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END
    
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
            text=f"🔔 You're already subscribed to _*[{esc_md(matches[0].name)}]({MAP_QUERY}{matches[0].name})*_",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        return ConversationHandler.END
    
    # If only one match and not subscribed
    if len(matches) == 1:
        port = matches[0]
        sub, created, err = subscribe_user_to_port(chat_id, port.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Subscribed to _*[{esc_md(port.name)}]({MAP_QUERY}{port.name})*_",
                reply_markup=get_back_to_menu_keyboard(),
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
            if not subs.get("vessels"):
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "⚠️ To receive notifications you also need at least *ONE* vessel subscription\\. Use the menu to add one\\."
                    ),
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ You've reached the maximum of *20* island subscriptions\\. Remove one to add more\\.",
                    reply_markup=get_back_to_menu_keyboard(),
                    parse_mode="MarkdownV2",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Failed to subscribe to _*{esc_md(port.name)}*_\\. Please try again shortly\\.",
                    reply_markup=get_back_to_menu_keyboard(),
                    parse_mode="MarkdownV2",
                )
        return ConversationHandler.END
    
    # Show already subscribed ports first
    msg_parts = []
    if already_subbed:
        msg_parts.append("*🔔 Already subscribed:*\n")
        for p in already_subbed:
            msg_parts.append(f"• _*[{esc_md(p.name)}]({MAP_QUERY}{p.name})*_")
    
    # Then show keyboard for available ones
    keyboard = []
    for p in available:
        keyboard.append(
            [InlineKeyboardButton(p.name, callback_data=f"sub_port:{p.id}")]
        )
    
    if not keyboard:
        # All matches are already subscribed
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(msg_parts),
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        return ConversationHandler.END
    
    msg = (
        "\n".join(msg_parts + ["", "*➕ Available islands to subscribe:*"])
        if msg_parts
        else "*➕ Choose an island to subscribe:*"
    )
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text=msg,
        reply_markup=reply_markup,
        parse_mode="MarkdownV2",
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def handle_vessel_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle vessel name input after 'Add Vessel' button."""
    chat = update.effective_chat
    user = update.effective_user
    chat_id = chat.id
    
    # Create user if needed
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
    
    q = update.message.text.strip()
    
    # Get user's current subscriptions
    subs = get_user_subscriptions(chat_id)
    subbed_vessels = {v.id: v for v in subs.get("vessels", [])}
    
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
            text=f"😕 No vessels found matching '{esc_md(q)}'\\. Try a shorter keyword\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END
    
    # If only one match and already subscribed
    if len(matches) == 1 and matches[0].id in subbed_vessels:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔔 You're already subscribed to _*[{esc_md(matches[0].name)}]({VESSEL_QUERY}{matches[0].id})*_",
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        return ConversationHandler.END
    
    # If only one match and not subscribed
    if len(matches) == 1:
        v = matches[0]
        sub, created, err = subscribe_user_to_vessel(chat_id, v.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Subscribed to _*[{esc_md(v.name)}]({VESSEL_QUERY}{v.id})*_",
                reply_markup=get_back_to_menu_keyboard(),
                parse_mode="MarkdownV2",
                disable_web_page_preview=True,
            )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ You've reached the maximum of *20* vessel subscriptions\\. Use the menu to remove one\\.",
                    reply_markup=get_back_to_menu_keyboard(),
                    parse_mode="MarkdownV2",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Failed to subscribe to vessel\\.",
                    reply_markup=get_back_to_menu_keyboard(),
                    parse_mode="MarkdownV2",
                )
        return ConversationHandler.END
    
    # Show already subscribed vessels first
    msg_parts = []
    if already_subbed:
        msg_parts.append("*🔔 Already subscribed:*")
        for v in already_subbed:
            msg_parts.append(f"• _*[{esc_md(v.name)}]({VESSEL_QUERY}{v.id})*_")
    
    # Then show keyboard for available ones
    keyboard = []
    for v in available:
        keyboard.append(
            [InlineKeyboardButton(f"{v.name}", callback_data=f"sub_vessel:{v.id}")]
        )
    
    if not keyboard:
        # All matches are already subscribed
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(msg_parts),
            reply_markup=get_back_to_menu_keyboard(),
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )
        return ConversationHandler.END
    
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
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def handle_island_stats_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle island name input for stats."""
    from .stats import island_stats as stats_func
    
    # Simulate args from user input
    context.args = update.message.text.strip().split()
    await stats_func(update, context)
    return ConversationHandler.END


async def handle_vessel_stats_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle vessel name input for stats."""
    from .stats import vessel_stats as stats_func
    
    # Simulate args from user input
    context.args = update.message.text.strip().split()
    await stats_func(update, context)
    return ConversationHandler.END


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation and return to menu."""
    await send_main_menu(update, context)
    return ConversationHandler.END

