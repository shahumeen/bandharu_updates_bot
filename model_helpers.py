# models_and_processor.py
from datetime import datetime
from zoneinfo import ZoneInfo
from models import *


def mv_time():
    return datetime.now(ZoneInfo("Indian/Maldives"))


def get_users_to_notify_for_log(port_log: PortLog):
    """Get the list of users who should be notified about a port log entry."""
    port = port_log.port
    vessel = port_log.vessel

    # 1) Users who are subscribed to this vessel AND have either:
    #    - a subscription to this specific port, or
    #    - no port subscriptions at all
    vessel_users = (
        User.select()
        .join(VesselSubscription)
        .where(
            (VesselSubscription.vessel == vessel)
            & (
                # Either user has this port in their subscriptions
                (
                    PortSubscription.select()
                    .where(
                        (PortSubscription.user == User)
                        & (PortSubscription.port == port)
                    )
                    .exists()
                )
                |
                # Or user has no port subscriptions at all
                ~(
                    PortSubscription.select()
                    .where(PortSubscription.user == User)
                    .exists()
                )
            )
        )
        .distinct()
    )

    # 2) Chats with main_port set to this port (additional notifications)
    # Note: Only groups can set main_port so no need to check chat_type
    group_main_port_users = User.select().where(User.main_port == port)

    # Combine all recipients, deduplicate by chat_id
    unique = {}

    # Add vessel subscribers (with matching port or no port subscriptions)
    for u in vessel_users:
        unique[u.chat_id] = u

    # Add group chats with matching main_port
    for u in group_main_port_users:
        unique[u.chat_id] = u

    return list(unique.values())


# If a vessel just arrived, ignore a transient 'departure' for this many seconds
PORT_EVENT_HYSTERESIS_SECONDS = 120


# -------------------------
# Helpers: initialize DB
# -------------------------
def initialize_db(create_tables=True):
    db.connect(reuse_if_open=True)
    if create_tables:
        # create all tables used by the application
        db.create_tables(
            [
                User,
                Port,
                Vessel,
                PortSubscription,
                VesselSubscription,
                PortLog,
                PortLogNotification,
            ],
            safe=True,
        )
    db.close()


# -------------------------
# Helper functions: Create and manage records
# -------------------------
def create_user(
    telegram_id: int,
    chat_type: str,
    username: str,
    first_name: str,
    last_name: str,
) -> User:
    """Create a new user if not exists, otherwise return existing user."""
    # User.chat_id is the primary key in the model
    user, created = User.get_or_create(
        chat_id=telegram_id,
        defaults={
            "chat_type": chat_type,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        },
    )
    return (user, created)


def create_port(name: str) -> Port:
    """Create a new port if not exists, otherwise return existing port."""
    # Port model only has a `name` column by default. Keep defaults usage
    # for forward compatibility if extra fields are added later.
    port, created = Port.get_or_create(name=name)
    return port


def create_vessel(
    vessel_id: int, name: str, vessel_type: str = None, contact: int = None
) -> Vessel:
    """Create a new vessel if not exists, otherwise update existing vessel."""
    vessel, created = Vessel.get_or_create(
        id=vessel_id,
        defaults={"name": name, "vessel_type": vessel_type, "contact": contact},
    )
    if not created:
        # Update vessel info if it already exists
        vessel.name = name
        vessel.vessel_type = vessel_type or vessel.vessel_type
        vessel.contact = contact or vessel.contact
        vessel.save()
    return vessel


def log_port_event(
    vessel: Vessel, port: Port, event: str, is_initial_sync: bool = False
) -> PortLog:
    """
    Create a new port log entry and update vessel's last port.
    event should be 'arrival' or 'departure'
    is_initial_sync: if True, marks the log as already notified (used during first data sync)
    """
    port_log = PortLog.create(
        vessel=vessel,
        port=port,
        event=event,
        notified=is_initial_sync,
    )

    # Update vessel's last known port and log id
    vessel.last_port = port
    vessel.last_port_log_id = port_log.id
    vessel.save()

    # def get_users_to_notify():
    #     port_users = (
    #         User.select().join(PortSubscription).where(PortSubscription.port == port)
    #     )
    #     vessel_users = (
    #         User.select()
    #         .join(VesselSubscription)
    #         .where(VesselSubscription.vessel == vessel)
    #     )
    #     return port_users | vessel_users

    for user in get_users_to_notify_for_log(port_log):
        PortLogNotification.get_or_create(
            port_log=port_log,
            user=user,
            sent=is_initial_sync,
        )

    return port_log


def get_vessel_location(vessel_id: int) -> tuple[Port, str, datetime] | None:
    """
    Get vessel's current location in database, last event and timestamp.
    Returns tuple of (port, event, timestamp) or None if no logs exist.
    """
    try:
        vessel = Vessel.get_by_id(vessel_id)
        if vessel.last_port_log_id:
            last_log = PortLog.get_by_id(vessel.last_port_log_id)
            return (last_log.port, last_log.event, last_log.timestamp)
    except (Vessel.DoesNotExist, PortLog.DoesNotExist):
        pass
    return None


def update_notified(
    user_or_chat: User | int | str, log_id: int, notified: bool = True
) -> bool:
    """
    Update the sent status of a PortLogNotification entry.

    user_or_chat can be a User instance or a chat_id (int/str). If a chat_id
    is provided we'll try to resolve the User record. Returns True if the
    update was successful, False if the entry wasn't found.
    """
    # Resolve user object if a raw chat id was provided
    user_obj = None
    try:
        if isinstance(user_or_chat, User):
            user_obj = user_or_chat
        else:
            # treat as chat id
            chat_id_val = int(user_or_chat)
            user_obj = User.get_or_none(User.chat_id == chat_id_val)
    except Exception:
        user_obj = None

    if user_obj is None:
        # nothing to update (no user record) — return False to signal no-op
        return False

    try:
        notification = PortLogNotification.get(
            (PortLogNotification.user == user_obj)
            & (PortLogNotification.port_log == log_id)
        )
        notification.sent = bool(notified)
        notification.notified_at = mv_time()
        notification.save()
        return True
    except PortLogNotification.DoesNotExist:
        return False


def update_port_logs(api_data: dict, is_initial_sync: bool = False):
    """
    For each vessel in api_data, compare its port info with the database and log arrivals/departures.
    If vessel's port in DB is not empty and API port is empty, log departure.
    If vessel's port in DB is empty and API port is not empty, log arrival.

    Args:
        api_data: Dictionary of vessel data from the API
        is_initial_sync: If True, marks all created logs as already notified
    """
    for vessel_id, vessel_info in api_data.items():
        try:
            vessel = Vessel.get_by_id(int(vessel_id))
        except Vessel.DoesNotExist:
            continue

        api_port_name = (
            vessel_info["port"]
            if "port" in vessel_info and vessel_info["port"] is not None
            else ""
        )
        db_location = get_vessel_location(vessel.id)

        # db_location is (port_obj, event, timestamp) or None
        prev_port = db_location[0] if db_location else None
        prev_event = db_location[1] if db_location else None

        # Normalize empty strings
        api_port_name = api_port_name.strip() if isinstance(api_port_name, str) else ""

        # Case A: previously at port (last event was an arrival)
        if prev_port and prev_event == "arrival":
            prev_port_name = prev_port.name
            # 1) Now at sea -> create a departure
            if not api_port_name:
                # Hysteresis: don't log a departure if the last arrival was very recent
                last_log = (
                    PortLog.get_by_id(vessel.last_port_log_id)
                    if vessel.last_port_log_id
                    else None
                )
                recent_arrival = False
                if last_log and last_log.event == "arrival":
                    try:
                        recent_arrival = (
                            mv_time() - last_log.timestamp
                        ).total_seconds() < PORT_EVENT_HYSTERESIS_SECONDS
                    except Exception:
                        recent_arrival = False

                if not recent_arrival:
                    port = Port.get_or_none(Port.name == prev_port_name)
                    if port:
                        log_port_event(vessel, port, "departure", is_initial_sync)

            # 2) Now at a different port -> departure then arrival
            elif api_port_name and api_port_name != prev_port_name:
                # If the arrival is immediate after a recent arrival, skip creating a departure
                last_log = (
                    PortLog.get_by_id(vessel.last_port_log_id)
                    if vessel.last_port_log_id
                    else None
                )
                recent_arrival = False
                if last_log and last_log.event == "arrival":
                    try:
                        recent_arrival = (
                            mv_time() - last_log.timestamp
                        ).total_seconds() < PORT_EVENT_HYSTERESIS_SECONDS
                    except Exception:
                        recent_arrival = False

                old_port = Port.get_or_none(Port.name == prev_port_name)
                new_port = create_port(api_port_name)
                if old_port and not recent_arrival:
                    log_port_event(vessel, old_port, "departure")
                # Always log arrival to the new port
                log_port_event(vessel, new_port, "arrival")

            # 3) Still at same port -> nothing to do

        # Case B: previously departed (last event was departure)
        elif prev_port and prev_event == "departure":
            # If API now shows still at sea -> nothing (already departed)
            if not api_port_name:
                pass
            # If API now shows arrival at some port -> create arrival only
            elif api_port_name:
                # If arrival is at same port as the departed one, still create arrival
                new_port = create_port(api_port_name)
                # Avoid creating duplicate arrival if last event was already arrival at same port
                last_log = (
                    PortLog.get_by_id(vessel.last_port_log_id)
                    if vessel.last_port_log_id
                    else None
                )
                if not (
                    last_log
                    and last_log.event == "arrival"
                    and last_log.port.name == api_port_name
                ):
                    log_port_event(vessel, new_port, "arrival", is_initial_sync)

        # Case C: no previous logs (unknown) -> create arrival if API shows a port
        else:
            if api_port_name:
                new_port = create_port(api_port_name)
                log_port_event(vessel, new_port, "arrival", is_initial_sync)


def subscribe_user_to_port(
    chat_id: int, port_id: int
) -> tuple[PortSubscription | None, bool]:
    """Subscribe the user (by chat_id) to the port (by id).

    Returns tuple (PortSubscription instance or None, created: bool).
    If the user does not exist returns (None, False).
    """
    user = User.get_or_none(User.chat_id == chat_id)
    if not user:
        return (None, False, "no_user")
    port = Port.get_or_none(Port.id == port_id)
    if not port:
        return (None, False, "no_port")
    # enforce max 10 port subscriptions per user
    current = PortSubscription.select().where(PortSubscription.user == user).count()
    if current >= 10:
        return (None, False, "limit_reached")
    sub, created = PortSubscription.get_or_create(user=user, port=port)
    return (sub, created, None)


def subscribe_user_to_vessel(
    chat_id: int, vessel_id: int
) -> tuple[VesselSubscription | None, bool]:
    """Subscribe the user (by chat_id) to the vessel (by id).

    Returns tuple (VesselSubscription instance or None, created: bool).
    If the user does not exist returns (None, False).
    """
    user = User.get_or_none(User.chat_id == chat_id)
    if not user:
        return (None, False, "no_user")
    vessel = Vessel.get_or_none(Vessel.id == vessel_id)
    if not vessel:
        return (None, False, "no_vessel")
    # enforce max 10 vessel subscriptions per user
    current = VesselSubscription.select().where(VesselSubscription.user == user).count()
    if current >= 10:
        return (None, False, "limit_reached")
    sub, created = VesselSubscription.get_or_create(user=user, vessel=vessel)
    return (sub, created, None)


def unsubscribe_user_from_port(chat_id: int, port_id: int) -> bool:
    """Remove a port subscription for a user/chat id. Returns True if deleted."""
    user = User.get_or_none(User.chat_id == chat_id)
    if not user:
        return False
    port = Port.get_or_none(Port.id == port_id)
    if not port:
        return False
    deleted = (
        PortSubscription.delete()
        .where((PortSubscription.user == user) & (PortSubscription.port == port))
        .execute()
    )
    return deleted > 0


def unsubscribe_user_from_vessel(chat_id: int, vessel_id: int) -> bool:
    """Remove a vessel subscription for a user/chat id. Returns True if deleted."""
    user = User.get_or_none(User.chat_id == chat_id)
    if not user:
        return False
    vessel = Vessel.get_or_none(Vessel.id == vessel_id)
    if not vessel:
        return False
    deleted = (
        VesselSubscription.delete()
        .where(
            (VesselSubscription.user == user) & (VesselSubscription.vessel == vessel)
        )
        .execute()
    )
    return deleted > 0


def set_main_port(chat_id: int, port_id: int) -> bool:
    """Set main_port for a group/channel user record. Returns True on success."""
    user = User.get_or_none(User.chat_id == chat_id)
    if not user:
        return False
    port = Port.get_or_none(Port.id == port_id)
    if not port:
        return False
    try:
        user.main_port = port
        user.save()
        return True
    except Exception:
        return False


def get_user_subscriptions(chat_id: int) -> dict:
    """Return a dict with lists of port and vessel subscriptions for a user/chat id.

    Example: {"ports": [port1, ...], "vessels": [vessel1, ...]}
    If user not found returns empty lists.
    """
    user = User.get_or_none(User.chat_id == chat_id)
    if not user:
        return {"ports": [], "vessels": []}
    ports = [
        ps.port for ps in PortSubscription.select().where(PortSubscription.user == user)
    ]
    vessels = [
        vs.vessel
        for vs in VesselSubscription.select().where(VesselSubscription.user == user)
    ]
    return {"ports": ports, "vessels": vessels}


if __name__ == "__main__":
    print(mv_time())
    initialize_db()
