from peewee import (
    SqliteDatabase,
    Model,
    AutoField,
    BigIntegerField,
    CharField,
    DateTimeField,
    BooleanField,
    ForeignKeyField,
    IntegerField,
    Check,
)
from datetime import datetime


def current_time():
    return datetime.now()


# -------------------------
# DB connection - SQLite only
# -------------------------
db = SqliteDatabase(
    "vessels_bot.db",
    pragmas={"journal_mode": "wal", "foreign_keys": 1},
)

print("Using SQLite database")


class BaseModel(Model):
    class Meta:
        database = db


class Port(BaseModel):
    id = AutoField()
    name = CharField(unique=True, max_length=255)

    @property
    def channel(self):
        """Get the channel (User) associated with this port, if any."""
        try:
            return User.get(User.main_port == self.id, User.chat_type == 'channel')
        except User.DoesNotExist:
            return None


class User(BaseModel):
    chat_id = BigIntegerField(unique=True, primary_key=True)
    chat_type = CharField(null=False, max_length=255)
    username = CharField(null=True, max_length=255)
    first_name = CharField(max_length=255)
    last_name = CharField(null=True, max_length=255)
    date_joined = DateTimeField(default=current_time)
    main_port = ForeignKeyField(
        Port, null=True, backref="main_port_chats", on_delete="CASCADE"
    )
    notify_on_departure = BooleanField(default=True)


class Vessel(BaseModel):
    id = BigIntegerField(null=False, unique=True, primary_key=True)
    name = CharField()
    vessel_type = CharField(null=True)
    contact = CharField(null=True)

    # Quick reference fields to avoid heavy joins:
    last_port = ForeignKeyField(
        Port, null=True, backref="vessels", on_delete="SET NULL"
    )
    last_port_log_id = IntegerField(
        null=True
    )  # store PortLog.id of the last known call


# --- Many-to-many subscription tables ---
class PortSubscription(BaseModel):
    """Many-to-many: user subscribes to many ports; port has many subscribers."""

    user = ForeignKeyField(User, backref="port_subscriptions", on_delete="CASCADE")
    port = ForeignKeyField(Port, backref="subscribers", on_delete="CASCADE")

    class Meta:
        # unique per user+port
        indexes = ((("user", "port"), True),)


class VesselSubscription(BaseModel):
    """Many-to-many: user subscribes to many vessels; vessel has many subscribers."""

    user = ForeignKeyField(User, backref="vessel_subscriptions", on_delete="CASCADE")
    vessel = ForeignKeyField(Vessel, backref="subscribers", on_delete="CASCADE")

    class Meta:
        indexes = ((("user", "vessel"), True),)


class PortLog(BaseModel):
    """One row per port event (arrival or departure or generic port call).
    Keep notified=False until the bot sends a notification for that event.
    """

    id = AutoField()
    timestamp = DateTimeField(default=current_time, index=True)
    vessel = ForeignKeyField(Vessel, backref="logs", on_delete="CASCADE")
    port = ForeignKeyField(Port, backref="logs", on_delete="CASCADE")
    event = CharField(
        null=False,
        constraints=[Check("event IN ('arrival', 'departure')")],
    )
    # Track whether this portlog has been marked as notified globally (optional)
    notified = BooleanField(default=False, index=True)


class PortLogNotification(BaseModel):
    """Track per-user notification status for each PortLog row."""

    port_log = ForeignKeyField(PortLog, backref="notifications", on_delete="CASCADE")
    user = ForeignKeyField(User, backref="notifications", on_delete="CASCADE")
    sent = BooleanField(default=False, index=True)
    notified_at = DateTimeField(default=current_time, index=True)

    class Meta:
        indexes = ((("port_log", "user"), True),)
