from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
)
from telegram.helpers import escape_markdown


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

load_dotenv()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
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
        "Hello! Welcome to the Vessel Update Bot.\n\n"
        "Use /subisland <name> to subscribe to island/port updates.\n"
        "Use /subvessel <name or id> to subscribe to a vessel.\n"
        "Use /settings to see your subscriptions."
    )
    await context.bot.send_message(chat_id=chat_id, text=text)


async def unrecognized_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle any messages that are not commands."""
    await update.message.reply_text(
        "Unrecognized command. Use /start to see available commands."
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
            chat_id=chat_id, text="Usage: /subisland <island name>"
        )
        return

    name = " ".join(context.args).strip()

    # Get all matching ports and user's current subscriptions
    matches = list(Port.select().where(Port.name.contains(name)).limit(10))
    subs = get_user_subscriptions(chat_id)
    subbed_ports = {p.id: p for p in subs.get("ports", [])}

    if not matches:
        await context.bot.send_message(
            chat_id=chat_id, text=f"No ports found matching '{name}'."
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
            chat_id=chat_id, text=f"You are already subscribed to {matches[0].name}."
        )
        return

    # If only one match and not subscribed
    if len(matches) == 1:
        port = matches[0]
        sub, created, err = subscribe_user_to_port(chat_id, port.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id, text=f"Subscribed to {port.name}."
            )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="You have reached the maximum of 10 port subscriptions.",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, text=f"Failed to subscribe to {port.name}."
                )
        return

    # Show already subscribed ports first
    msg_parts = []
    if already_subbed:
        msg_parts.append("Already subscribed to:")
        for p in already_subbed:
            msg_parts.append(f"- {p.name}")

    # Then show keyboard for available ones
    keyboard = []
    for p in available:
        keyboard.append(
            [InlineKeyboardButton(p.name, callback_data=f"sub_port:{p.id}")]
        )

    if not keyboard:
        # All matches are already subscribed
        await context.bot.send_message(chat_id=chat_id, text="\n".join(msg_parts))
        return

    msg = (
        "\n".join(msg_parts + ["", "Available ports to subscribe:"])
        if msg_parts
        else "Choose a port to subscribe:"
    )
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=reply_markup)


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
            chat_id=chat_id, text="Usage: /subvessel <vessel name or id>"
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
                chat_id=chat_id, text=f"Vessel with id {q} not found."
            )
            return

        if v.id in subbed_vessels:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"You are already subscribed to {v.name} ({v.id}).",
            )
            return

        sub, created, err = subscribe_user_to_vessel(chat_id, v.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id, text=f"Subscribed to vessel {v.name} ({v.id})."
            )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="You have reached the maximum of 10 vessel subscriptions.",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, text="Failed to subscribe to vessel."
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
            chat_id=chat_id, text=f"No vessels found matching '{q}'."
        )
        return

    # If only one match and already subscribed
    if len(matches) == 1 and matches[0].id in subbed_vessels:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"You are already subscribed to {matches[0].name} ({matches[0].id}).",
        )
        return

    # If only one match and not subscribed
    if len(matches) == 1:
        v = matches[0]
        sub, created, err = subscribe_user_to_vessel(chat_id, v.id)
        if sub:
            await context.bot.send_message(
                chat_id=chat_id, text=f"Subscribed to vessel {v.name} ({v.id})."
            )
        else:
            if err == "limit_reached":
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="You have reached the maximum of 10 vessel subscriptions.",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id, text="Failed to subscribe to vessel."
                )
        return

    # Show already subscribed vessels first
    msg_parts = []
    if already_subbed:
        msg_parts.append("Already subscribed to:")
        for v in already_subbed:
            msg_parts.append(f"- {v.name} ({v.id})")

    # Then show keyboard for available ones
    keyboard = []
    for v in available:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{v.name} ({v.id})", callback_data=f"sub_vessel:{v.id}"
                )
            ]
        )

    if not keyboard:
        # All matches are already subscribed
        await context.bot.send_message(chat_id=chat_id, text="\n".join(msg_parts))
        return

    msg = (
        "\n".join(msg_parts + ["", "Available vessels to subscribe:"])
        if msg_parts
        else "Choose a vessel to subscribe:"
    )
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text=msg,
        reply_markup=reply_markup,
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    chat_id = chat.id
    subs = get_user_subscriptions(chat_id)
    port_list = subs.get("ports", [])
    vessel_list = subs.get("vessels", [])

    def esc(s):
        return escape_markdown(str(s), version=2)

    lines = ["Your subscriptions:\n"]
    if port_list:
        lines.append("Ports:")
        for p in port_list:
            lines.append(f" \\- {esc(p.name)}")
    else:
        lines.append("Ports: None")

    if vessel_list:
        lines.append("\nVessels:")
        for v in vessel_list:
            lines.append(f" \\- {esc(v.name)}")
    else:
        lines.append("\nVessels: None")

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
                    f"Unsub {p.name}", callback_data=f"unsub_port:{p.id}"
                )
            ]
        )
    for v in vessel_list:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"Unsub {v.name}", callback_data=f"unsub_vessel:{v.id}"
                )
            ]
        )

    if not keyboard:
        await context.bot.send_message(
            chat_id=chat_id, text="You have no subscriptions to unsubscribe."
        )
        return

    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text="Choose a subscription to remove:",
        reply_markup=reply_markup,
    )


async def findchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for a port and get its channel information if it exists.
    Usage: /findchannel <port name>"""
    chat = update.effective_chat
    chat_id = chat.id

    if not context.args:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Usage: /findchannel <port name>\nExample: /findchannel Male",
        )
        return

    port_name = " ".join(context.args).strip()

    # Find matching ports
    matches = list(Port.select().where(Port.name.contains(port_name)))

    if not matches:
        await context.bot.send_message(
            chat_id=chat_id, text=f"No ports found matching '{port_name}'"
        )
        return

    if len(matches) == 1:
        port = matches[0]
        channel = port.channel
        if channel:
            await context.bot.send_message(
                chat_id=chat_id, text=f"Channel for {port.name}: @{channel.username}"
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"No channel found for {port.name} :(\nPlease request @shahumeen to make a channel for {port.name}",
            )
    else:
        # Show keyboard for multiple matches
        keyboard = []
        for p in matches:
            keyboard.append(
                [InlineKeyboardButton(p.name, callback_data=f"get_port_channel:{p.id}")]
            )

        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Multiple ports found matching '{port_name}'. Please select one:",
            reply_markup=reply_markup,
        )


async def channelsubvessel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to subscribe a channel to a vessel.
    Usage: /channelsubvessel channel_username vessel_name"""
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="This command can only be used by admin"
        )
        return

    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Usage: /channelsubvessel channel_username vessel_name\nExample: /channelsubvessel channel1 speedstar",
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
                text=f"Channel @{channel_username} not found. Please add it first using /addchannel",
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
                chat_id=chat_id, text=f"No vessels found matching '{vessel_name}'."
            )
            return

        # If only one match and already subscribed
        if len(matches) == 1 and matches[0].id in subbed_vessels:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Channel @{channel_username} is already subscribed to {matches[0].name} ({matches[0].id}).",
            )
            return

        # If only one match and not subscribed
        if len(matches) == 1:
            v = matches[0]
            sub, created, err = subscribe_user_to_vessel(channel.chat_id, v.id)
            if sub:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Channel @{channel_username} subscribed to vessel {v.name} ({v.id}).",
                )
            else:
                if err == "limit_reached":
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="Channel has reached the maximum of 10 vessel subscriptions.",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id, text="Failed to subscribe channel to vessel."
                    )
            return

        # Show keyboard for multiple matches
        keyboard = []
        for v in matches:
            if v.id not in subbed_vessels:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"{v.name} ({v.id})",
                            callback_data=f"channel_sub_vessel:{channel.chat_id}:{v.id}",
                        )
                    ]
                )

        if not keyboard:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Channel @{channel_username} is already subscribed to all matching vessels.",
            )
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Choose a vessel to subscribe channel @{channel_username} to:",
            reply_markup=reply_markup,
        )

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Invalid channel username format",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {str(e)}")


async def channelsubisland(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to subscribe a channel to a port/island.
    Usage: /channelsubisland channel_username port_name"""
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="This command can only be used by admin"
        )
        return

    if len(context.args) < 2:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Usage: /channelsubisland channel_username port_name\nExample: /channelsubisland channel1 male",
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
                text=f"Channel @{channel_username} not found. Please add it first using /addchannel",
            )
            return

        # Get all matching ports and channel's current subscriptions
        matches = list(Port.select().where(Port.name.contains(port_name)).limit(10))
        subs = get_user_subscriptions(channel.chat_id)
        subbed_ports = {p.id: p for p in subs.get("ports", [])}

        if not matches:
            await context.bot.send_message(
                chat_id=chat_id, text=f"No ports found matching '{port_name}'."
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
                    text=f"Channel @{channel_username} subscribed to {port.name}.",
                )
            else:
                if err == "limit_reached":
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="Channel has reached the maximum of 10 port subscriptions.",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"Failed to subscribe channel to {port.name}.",
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
                text=f"Channel @{channel_username} is already subscribed to all matching ports.",
            )
            return

        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"Choose a port to subscribe channel @{channel_username} to:",
            reply_markup=reply_markup,
        )

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Invalid channel username format",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {str(e)}")


async def addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a channel as a user and set its main port. Admin only command.
    Usage: /addchannel port_name channel_id channel_username"""
    chat = update.effective_chat
    chat_id = chat.id

    if int(chat_id) != int(ADMIN_CHAT_ID):
        await context.bot.send_message(
            chat_id=chat_id, text="This command can only be used by admin"
        )
        return

    # Check if correct number of arguments provided
    if len(context.args) != 3:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Usage: /addchannel port_name channel_id channel_username\nExample: /addchannel Male -10012345674490 @male_port",
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
                chat_id=chat_id, text=f"No ports found matching '{port_name}'"
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
                text=f"Multiple ports found matching '{port_name}'. Please select one:",
                reply_markup=reply_markup,
            )
            return

        # Create or update the user
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
            text=f"Successfully {'added' if created else 'updated'} channel {channel_username} for port {port_name}",
        )

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Invalid channel ID format. Please provide a valid integer ID",
        )
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {str(e)}")


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
                await cq.edit_message_text(text=f"Subscribed to port (id={pid}).")
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="You have reached the maximum of 10 port subscriptions."
                    )
                else:
                    await cq.edit_message_text(
                        text=f"Failed to subscribe to port (id={pid})."
                    )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("sub_vessel:"):
        try:
            vid = int(data.split(":", 1)[1])
            sub, created, err = subscribe_user_to_vessel(click_id, vid)
            if sub:
                await cq.edit_message_text(text=f"Subscribed to vessel (id={vid}).")
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="You have reached the maximum of 10 vessel subscriptions."
                    )
                else:
                    await cq.edit_message_text(
                        text=f"Failed to subscribe to vessel (id={vid})."
                    )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("unsub_port:"):
        try:
            pid = int(data.split(":", 1)[1])
            ok = unsubscribe_user_from_port(click_id, pid)
            if ok:
                await cq.edit_message_text(text=f"Unsubscribed from port (id={pid}).")
            else:
                await cq.edit_message_text(
                    text=f"Failed to unsubscribe from port (id={pid})."
                )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("unsub_vessel:"):
        try:
            vid = int(data.split(":", 1)[1])
            ok = unsubscribe_user_from_vessel(click_id, vid)
            if ok:
                await cq.edit_message_text(text=f"Unsubscribed from vessel (id={vid}).")
            else:
                await cq.edit_message_text(
                    text=f"Failed to unsubscribe from vessel (id={vid})."
                )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("add_channel:"):
        try:
            _, channel_id, channel_username, port_id = data.split(":")
            channel_id = int(channel_id)
            port_id = int(port_id)

            try:
                port = Port.get_by_id(port_id)
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
                    text=f"Successfully {'added' if created else 'updated'} channel {channel_username} for port {port.name}"
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
                await cq.edit_message_text(text=f"Main port set to id={pid}.")
            else:
                await cq.edit_message_text(text=f"Failed to set main port (id={pid}).")
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
                await cq.edit_message_text(
                    text=f"Channel (id={channel_id}) subscribed to vessel (id={vid})."
                )
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="Channel has reached the maximum of 10 vessel subscriptions."
                    )
                else:
                    await cq.edit_message_text(
                        text=f"Failed to subscribe channel to vessel (id={vid})."
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
                await cq.edit_message_text(
                    text=f"Channel (id={channel_id}) subscribed to port (id={pid})."
                )
            else:
                if err == "limit_reached":
                    await cq.edit_message_text(
                        text="Channel has reached the maximum of 10 port subscriptions."
                    )
                else:
                    await cq.edit_message_text(
                        text=f"Failed to subscribe channel to port (id={pid})."
                    )
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")

    elif data.startswith("get_port_channel:"):
        try:
            port_id = int(data.split(":", 1)[1])
            try:
                port = Port.get_by_id(port_id)
                channel = port.channel
                if channel:
                    await cq.edit_message_text(
                        text=f"Channel for {port.name}: {channel.username}"
                    )
                else:
                    await cq.edit_message_text(text=f"No channel found for {port.name}")
            except Port.DoesNotExist:
                await cq.edit_message_text(text=f"Error: Port not found")
        except Exception:
            await cq.edit_message_text(text="Invalid selection.")
