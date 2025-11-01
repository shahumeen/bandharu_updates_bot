from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
from model_helpers import Port, PortLog, Vessel, mv_time


def get_daily_port_stats(port_id: int, peak_limit: int = 5) -> dict:
    """
    Generate a statistics report for a specific port.
    Returns a dict with all stats for later formatting.
    """
    # Get yesterday's date range in MV time
    now = mv_time()
    yesterday = now.date() - timedelta(days=1)
    mv_tz = ZoneInfo("Indian/Maldives")
    start_time = datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=mv_tz)
    end_time = datetime.combine(yesterday, datetime.max.time()).replace(tzinfo=mv_tz)

    # Helper function to ensure datetime objects
    def ensure_datetime(ts) -> datetime:
        if isinstance(ts, str):
            return datetime.fromisoformat(ts).replace(tzinfo=mv_tz)
        elif isinstance(ts, datetime):
            return ts.replace(tzinfo=mv_tz) if ts.tzinfo is None else ts
        raise ValueError(f"Cannot convert {type(ts)} to datetime")

    # Get all logs for yesterday
    logs = list(
        PortLog.select(PortLog, Vessel, Port)
        .join(Vessel)
        .switch(PortLog)
        .join(Port)
        .where(
            (PortLog.port_id == port_id)
            & (PortLog.timestamp >= start_time)
            & (PortLog.timestamp <= end_time)
        )
        .order_by(PortLog.timestamp)
        .execute()
    )

    if not logs:
        return {"error": "No activity recorded for yesterday."}

    # Initialize data structures
    hourly_counts = defaultdict(int)
    vessel_trips = defaultdict(int)
    vessel_longest_trip = {}
    destination_counts = defaultdict(int)
    vessel_destinations = defaultdict(list)
    vessel_type_trips = defaultdict(int)  # vessel_type -> trip count

    # Process logs
    for log in logs:
        # Convert timestamp to proper datetime and get hour
        log_time = ensure_datetime(log.timestamp)
        hour_dt = log_time.replace(minute=0, second=0, microsecond=0)
        hourly_counts[hour_dt] += 1

        if log.event == "arrival" and log.port.id == port_id:
            vessel_trips[log.vessel.name] += 1
            # Count vessel type for this trip
            vessel_type = (
                getattr(log.vessel, "vessel_type", None)
                or getattr(log.vessel, "type", None)
                or "Unknown"
            )
            vessel_type_trips[vessel_type] += 1

            # Find the previous departure for this vessel to calculate trip duration
            prev_departure = (
                PortLog.select()
                .where(
                    (PortLog.vessel == log.vessel)
                    & (PortLog.event == "departure")
                    & (PortLog.timestamp < log.timestamp)
                    & (PortLog.port_id != port_id)  # Must be from a different port
                )
                .order_by(PortLog.timestamp.desc())  # Get the most recent departure
                .first()
            )

            if prev_departure:
                # Convert timestamps to proper datetime objects
                prev_departure_time = ensure_datetime(prev_departure.timestamp)
                duration = (log_time - prev_departure_time).total_seconds()
                trip = {
                    "from": prev_departure.port.name,
                    "to": log.port.name,
                    "duration": duration,
                    "vessel": log.vessel.name,
                }

                # Count the origin port as a destination (since it's where the vessel came from)
                destination_counts[prev_departure.port.name] += 1
                vessel_destinations[log.vessel.name].append(prev_departure.port.name)

                if (
                    log.vessel.name not in vessel_longest_trip
                    or duration > vessel_longest_trip[log.vessel.name]["duration"]
                ):
                    vessel_longest_trip[log.vessel.name] = trip

    # Calculate statistics
    busiest_hour = (
        max(hourly_counts.items(), key=lambda x: x[1]) if hourly_counts else None
    )
    most_active_vessel = (
        max(vessel_trips.items(), key=lambda x: x[1]) if vessel_trips else None
    )
    longest_trip = (
        max(vessel_longest_trip.values(), key=lambda x: x["duration"])
        if vessel_longest_trip
        else None
    )
    most_popular_island = (
        max(destination_counts.items(), key=lambda x: x[1])
        if destination_counts
        else None
    )

    # Create leaderboard
    leaderboard = [
        {"vessel": vessel, "trips": trips}
        for vessel, trips in sorted(
            vessel_trips.items(), key=lambda x: x[1], reverse=True
        )[:3]
    ]

    # Format peak hours - select the top `peak_limit` busiest hours
    # 1) Sort by count descending and take at most `peak_limit` entries
    # 2) Sort the selected top entries chronologically (by hour) for display
    top_hours = sorted(hourly_counts.items(), key=lambda x: x[1], reverse=True)[
        :peak_limit
    ]
    peak_hours = [
        {
            "hour": hour_dt.strftime("%H:%M"),
            "count": count,
            "vessel_word": "vessel" if count == 1 else "vessels",
            "is_busiest": (hour_dt, count) == busiest_hour,
        }
        for hour_dt, count in sorted(top_hours, key=lambda x: x[0])
    ]
    max_vessels = max(hourly_counts.values()) if hourly_counts else 0

    def format_duration(seconds: float) -> str:
        minutes = int((seconds % 3600) // 60)
        total_hours = int(seconds // 3600)
        days = total_hours // 24
        hours = total_hours % 24

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")

        # If duration is 0, show 0m
        if not parts:
            return "0m"

        return " ".join(parts)

    # No need for format_bar in dict output

    # Compose the result dict
    total_trips = sum(vessel_trips.values())
    total_vessels = len(set(log.vessel.id for log in logs))

    result = {
        "date": yesterday.strftime("%d %b %Y"),
        "busiest_hour": None,
        "most_active": None,
        "longest_trip": None,
        "most_popular_island": None,
        "leaderboard": leaderboard,
        "peak_hours": peak_hours,
        "total_trips": total_trips,
        "unique_vessels": total_vessels,
        "vessel_type_trips": dict(
            sorted(vessel_type_trips.items(), key=lambda x: (-x[1], x[0]))
        ),
    }

    if busiest_hour:
        vessel_word = "vessel" if busiest_hour[1] == 1 else "vessels"
        result["busiest_hour"] = (
            f"{busiest_hour[0].strftime('%H:%M')}-{(busiest_hour[0] + timedelta(hours=1)).strftime('%H:%M')} ({busiest_hour[1]} {vessel_word})"
        )

    if most_active_vessel:
        trip_word = "trip" if most_active_vessel[1] == 1 else "trips"
        result["most_active"] = (
            f"{most_active_vessel[0]} ({most_active_vessel[1]} {trip_word})"
        )

    if longest_trip:
        result["longest_trip"] = {
            "vessel": longest_trip["vessel"],
            "from": longest_trip["from"],
            "to": longest_trip["to"],
            "duration": format_duration(longest_trip["duration"]),
        }

    if most_popular_island:
        trip_word = "trip" if most_popular_island[1] == 1 else "trips"
        result["most_popular_island"] = (
            f"{most_popular_island[0]} ({most_popular_island[1]} {trip_word})"
        )

    return result


if __name__ == "__main__":
    # Example usage:
    port_id = 2  # Replace with actual port ID
    import pprint

    pprint.pprint(get_daily_port_stats(port_id))
