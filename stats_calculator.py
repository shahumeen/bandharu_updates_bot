from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
from model_helpers import Port, PortLog, Vessel, current_time


def get_daily_port_stats(port_id: int, peak_limit: int = 5) -> dict:
    """
    Generate a statistics report for a specific port.
    Returns a dict with all stats for later formatting.
    """
    # Get yesterday's date range in MV time
    mv_tz = ZoneInfo("Indian/Maldives")
    now = datetime.now(timezone.utc).astimezone(mv_tz)
    yesterday = now.date() - timedelta(days=1)
    start_time = datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=mv_tz)
    end_time = datetime.combine(yesterday, datetime.max.time()).replace(tzinfo=mv_tz)

    # Convert MV-local window to UTC for DB filtering (if DB stores timestamps in UTC)
    utc = ZoneInfo("UTC")
    start_time_utc = start_time.astimezone(utc)
    end_time_utc = end_time.astimezone(utc)

    # Helper function to ensure datetime objects
    def ensure_datetime(ts) -> datetime:
        """Return an aware datetime without forcing Maldives tz.

        - If ts is a string, parse ISO (supporting trailing 'Z').
        - If naive, assume UTC (common DB convention) to avoid shifting.
        - Do NOT set Maldives tz here; we'll convert with .astimezone(mv_tz) at use sites.
        """
        if isinstance(ts, str):
            s = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
        elif isinstance(ts, datetime):
            dt = ts
        else:
            raise ValueError(f"Cannot convert {type(ts)} to datetime")

        if dt.tzinfo is None:
            # Assume UTC for naive timestamps
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    # Get all logs for yesterday
    logs = list(
        PortLog.select(PortLog, Vessel, Port)
        .join(Vessel)
        .switch(PortLog)
        .join(Port)
        .where(
            (PortLog.port_id == port_id)
            & (PortLog.timestamp >= start_time_utc)
            & (PortLog.timestamp <= end_time_utc)
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
        # Always convert to Maldives timezone for bucketing and display
        log_time = ensure_datetime(log.timestamp).astimezone(mv_tz)
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
                prev_departure_time = ensure_datetime(
                    prev_departure.timestamp
                ).astimezone(mv_tz)
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
    # --- Busiest hour(s) ---
    busiest_hour = (
        max(hourly_counts.items(), key=lambda x: x[1]) if hourly_counts else None
    )
    max_hour_count = max(hourly_counts.values()) if hourly_counts else None
    busiest_hours_list = (
        [dt for dt, c in hourly_counts.items() if c == max_hour_count]
        if max_hour_count is not None
        else []
    )

    # --- Most active vessel(s) ---
    most_active_vessel = (
        max(vessel_trips.items(), key=lambda x: x[1]) if vessel_trips else None
    )
    max_vessel_trips = max(vessel_trips.values()) if vessel_trips else None
    most_active_vessels_list = (
        [v for v, t in vessel_trips.items() if t == max_vessel_trips]
        if max_vessel_trips is not None
        else []
    )

    # --- Longest trip (ties possible) ---
    longest_trip = (
        max(vessel_longest_trip.values(), key=lambda x: x["duration"])
        if vessel_longest_trip
        else None
    )
    max_trip_duration = (
        max((trip["duration"] for trip in vessel_longest_trip.values()))
        if vessel_longest_trip
        else None
    )
    longest_trip_ties = (
        [
            trip
            for trip in vessel_longest_trip.values()
            if trip["duration"] == max_trip_duration
        ]
        if max_trip_duration is not None
        else []
    )

    # --- Most popular island(s) ---
    most_popular_island = (
        max(destination_counts.items(), key=lambda x: x[1])
        if destination_counts
        else None
    )
    max_destination_count = (
        max(destination_counts.values()) if destination_counts else None
    )
    most_popular_islands_list = (
        [
            name
            for name, cnt in destination_counts.items()
            if cnt == max_destination_count
        ]
        if max_destination_count is not None
        else []
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
            # mark busiest for ALL ties, not just one
            "is_busiest": count == max_hour_count,
        }
        for hour_dt, count in sorted(top_hours, key=lambda x: x[0])
    ]
    max_vessels = max_hour_count if max_hour_count is not None else 0

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
        "busiest_hour": None,  # kept for backward compatibility (single formatted string)
        "busiest_hours": [
            (dt.strftime("%H:%M"), (dt + timedelta(hours=1)).strftime("%H:%M"))
            for dt in sorted(busiest_hours_list)
        ],  # list of tuples (start,end) for ties
        "most_active": None,  # legacy single string
        "most_active_vessels": sorted(most_active_vessels_list),  # list for ties
        "longest_trip": None,
        "longest_trip_ties": longest_trip_ties,  # list of raw trip dicts (duration seconds)
        "most_popular_island": None,
        "most_popular_islands": sorted(most_popular_islands_list),  # list for ties
        "leaderboard": leaderboard,
        "peak_hours": peak_hours,
        "total_trips": total_trips,
        "unique_vessels": total_vessels,
        "vessel_type_trips": dict(
            sorted(vessel_type_trips.items(), key=lambda x: (-x[1], x[0]))
        ),
        # raw structures useful for downstream tie logic / future analytics
        "hourly_counts": {dt.isoformat(): c for dt, c in hourly_counts.items()},
        "destination_counts": dict(
            sorted(destination_counts.items(), key=lambda x: (-x[1], x[0]))
        ),
        "vessel_trips": dict(sorted(vessel_trips.items(), key=lambda x: (-x[1], x[0]))),
    }

    if busiest_hour:
        vessel_word = "vessel" if busiest_hour[1] == 1 else "vessels"
        result["busiest_hour"] = (
            f"{busiest_hour[0].strftime('%H:%M')}-{(busiest_hour[0] + timedelta(hours=1)).strftime('%H:%M')} ({busiest_hour[1]} {vessel_word})"
        )

    if most_active_vessel:
        trip_word = "trip" if most_active_vessel[1] == 1 else "trips"
        if len(most_active_vessels_list) > 1:
            vessels_joined = ", ".join(sorted(most_active_vessels_list))
            result["most_active"] = (
                f"Tie: {vessels_joined} ({most_active_vessel[1]} {trip_word})"
            )
        else:
            result["most_active"] = (
                f"{most_active_vessel[0]} ({most_active_vessel[1]} {trip_word})"
            )

    if longest_trip:
        if len(longest_trip_ties) > 1:
            # Format a combined tie description
            tie_parts = []
            for trip in sorted(longest_trip_ties, key=lambda x: x["vessel"]):
                tie_parts.append(
                    f"{trip['vessel']} ({trip['from']} → {trip['to']}, {format_duration(trip['duration'])})"
                )
            result["longest_trip"] = {
                "tie": True,
                "description": "Tie: " + "; ".join(tie_parts),
                "duration": format_duration(longest_trip["duration"]),
            }
        else:
            result["longest_trip"] = {
                "vessel": longest_trip["vessel"],
                "from": longest_trip["from"],
                "to": longest_trip["to"],
                "duration": format_duration(longest_trip["duration"]),
                "tie": False,
            }

    if most_popular_island:
        trip_word = "trip" if most_popular_island[1] == 1 else "trips"
        if len(most_popular_islands_list) > 1:
            islands_joined = ", ".join(sorted(most_popular_islands_list))
            result["most_popular_island"] = (
                f"Tie: {islands_joined} ({most_popular_island[1]} {trip_word})"
            )
        else:
            result["most_popular_island"] = (
                f"{most_popular_island[0]} ({most_popular_island[1]} {trip_word})"
            )
    return result

def get_vessel_stats(vessel_id: int, peak_limit: int = 5) -> dict:
    """Get last 7 days statistics for a vessel.

    Returns a dict with:
      - period: ISO strings for window start/end (MV local)
      - inactive: bool and message if no travel (always in port)
      - history: ordered list of islands visited by arrival time (compact with counts)
      - active_time: formatted total time spent traveling in window
      - active_time_seconds: raw seconds
      - longest_trip: best trip dict (from, to, duration formatted and seconds)
      - activity_hours: top hours-of-day by travel minutes (like peak hours)
      - hourly_travel_seconds: raw 0..23 mapping
    """
    mv_tz = ZoneInfo("Indian/Maldives")
    utc = ZoneInfo("UTC")

    now_mv = datetime.now(timezone.utc).astimezone(mv_tz)
    # Use last midnight as the window end, and 7 days before that as start
    window_end_mv = now_mv.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start_mv = window_end_mv - timedelta(days=7)

    # Convert window to UTC for DB filtering
    window_start_utc = window_start_mv.astimezone(utc)
    window_end_utc = window_end_mv.astimezone(utc)

    def ensure_datetime(ts) -> datetime:
        """Normalize timestamps to aware datetimes.

        - Strings parsed as ISO (support trailing Z)
        - Naive assumed UTC
        - Do not set MV tz here; convert on use with .astimezone(mv_tz)
        """
        if isinstance(ts, str):
            s = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
        elif isinstance(ts, datetime):
            dt = ts
        else:
            raise ValueError(f"Cannot convert {type(ts)} to datetime")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

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
        if not parts:
            return "0m"
        return " ".join(parts)

    # 1) Fetch required logs
    # Last log before window start to determine state at boundary
    last_before = (
        PortLog.select()
        .where((PortLog.vessel == vessel_id) & (PortLog.timestamp < window_start_utc))
        .order_by(PortLog.timestamp.desc())
        .first()
    )

    # All logs within the window (inclusive)
    logs_in_window = list(
        PortLog.select(PortLog)
        .where(
            (PortLog.vessel == vessel_id)
            & (PortLog.timestamp >= window_start_utc)
            & (PortLog.timestamp <= window_end_utc)
        )
        .order_by(PortLog.timestamp)
    )

    # 2) Build travel intervals (at sea) clipped to window
    at_sea = False
    current_start_mv: datetime | None = None
    last_departure_mv: datetime | None = None
    last_departure_port: str | None = None
    travel_intervals: list[tuple[datetime, datetime]] = []

    if last_before is not None:
        lb_time_mv = ensure_datetime(last_before.timestamp).astimezone(mv_tz)
        if last_before.event == "departure":
            at_sea = True
            # began before the window; starts counting at window start
            current_start_mv = window_start_mv
            last_departure_mv = lb_time_mv
            last_departure_port = getattr(last_before.port, "name", None)

    # Iterate logs within the window chronologically
    for log in logs_in_window:
        log_time_mv = ensure_datetime(log.timestamp).astimezone(mv_tz)
        if log.event == "departure":
            # If already at sea, ignore duplicate departures
            if not at_sea:
                at_sea = True
                current_start_mv = max(log_time_mv, window_start_mv)
                last_departure_mv = log_time_mv
                last_departure_port = getattr(log.port, "name", None)
        elif log.event == "arrival":
            if at_sea and current_start_mv is not None:
                end_mv = min(log_time_mv, window_end_mv)
                if end_mv > current_start_mv:
                    travel_intervals.append((current_start_mv, end_mv))
            # Reset sea state regardless
            at_sea = False
            current_start_mv = None

    # If still at sea at window end, close interval at window_end
    if at_sea and current_start_mv is not None:
        end_mv = window_end_mv
        if end_mv > current_start_mv:
            travel_intervals.append((current_start_mv, end_mv))

    # 3) Compute total active time
    active_seconds = 0
    for s, e in travel_intervals:
        active_seconds += (e - s).total_seconds()

    # 4) Build activity graph by hour-of-day across the window
    hourly_travel_seconds = {h: 0 for h in range(24)}

    def accumulate_hourly(start_mv: datetime, end_mv: datetime):
        cur = start_mv
        while cur < end_mv:
            hour_start = cur.replace(minute=0, second=0, microsecond=0)
            next_hour = hour_start + timedelta(hours=1)
            chunk_end = min(next_hour, end_mv)
            seconds = (chunk_end - cur).total_seconds()
            hourly_travel_seconds[hour_start.hour] += int(seconds)
            cur = chunk_end

    for s, e in travel_intervals:
        accumulate_hourly(s, e)

    # 5) Vessel history and visited island counts
    arrival_logs = [
        log for log in logs_in_window if getattr(log, "event", None) == "arrival"
    ]
    history_compact = []
    seen = {}
    for log in arrival_logs:
        log_time_mv = ensure_datetime(log.timestamp).astimezone(mv_tz)
        port_name = getattr(log.port, "name", None) if hasattr(log, "port") else None
        if not port_name:
            continue
        if port_name not in seen:
            seen[port_name] = {"port": port_name, "count": 1, "first_arrival": log_time_mv}
        else:
            seen[port_name]["count"] += 1
    # order by first arrival time
    history_compact = [
        {
            "port": v["port"],
            "count": v["count"],
            "first_arrival": v["first_arrival"].strftime("%d %b %Y %H:%M"),
        }
        for v in sorted(seen.values(), key=lambda x: x["first_arrival"])
    ]

    # Visited islands ranked by number of arrivals (dense ranking)
    visited_counts = {name: data["count"] for name, data in seen.items()}
    ranked = sorted(visited_counts.items(), key=lambda x: (-x[1], x[0]))
    visited_islands_ranked = []
    prev_count = None
    rank = 0
    for name, cnt in ranked:
        if prev_count is None:
            rank = 1
        elif cnt < prev_count:
            rank += 1
        prev_count = cnt
        visited_islands_ranked.append({"rank": rank, "port": name, "count": cnt})

    most_visited_count = max(visited_counts.values()) if visited_counts else 0
    most_visited_islands = (
        sorted([n for n, c in visited_counts.items() if c == most_visited_count])
        if most_visited_count > 0
        else []
    )

    # 6) Longest trip in the window (completed trips whose arrival is in window)
    longest_trip = None
    longest_seconds = -1
    for log in arrival_logs:
        arr_time_mv = ensure_datetime(log.timestamp).astimezone(mv_tz)
        # previous departure for this vessel before this arrival
        prev_dep = (
            PortLog.select()
            .where(
                (PortLog.vessel == vessel_id)
                & (PortLog.event == "departure")
                & (PortLog.timestamp < log.timestamp)
            )
            .order_by(PortLog.timestamp.desc())
            .first()
        )
        if not prev_dep:
            continue
        dep_time_mv = ensure_datetime(prev_dep.timestamp).astimezone(mv_tz)
        duration = (arr_time_mv - dep_time_mv).total_seconds()
        if duration > longest_seconds:
            longest_seconds = int(duration)
            longest_trip = {
                "from": getattr(prev_dep.port, "name", None),
                "to": getattr(log.port, "name", None),
                "duration": format_duration(duration),
                "duration_seconds": int(duration),
                "arrival": arr_time_mv.strftime("%d %b %Y %H:%M"),
                "departure": dep_time_mv.strftime("%d %b %Y %H:%M"),
            }

    # 7) Activity hours similar to peak_hours (top N by total minutes traveling)
    max_sec = max(hourly_travel_seconds.values()) if hourly_travel_seconds else 0
    top_hours = sorted(hourly_travel_seconds.items(), key=lambda x: x[1], reverse=True)[:peak_limit]
    activity_hours = [
        {
            "hour": f"{h:02d}:00",
            "minutes": secs // 60,
            "seconds": secs,
            "is_peak": secs == max_sec and max_sec > 0,
        }
        for h, secs in sorted(top_hours, key=lambda x: x[0])
    ]

    # 7b) Daily trips (arrivals per day) for the last 7 full days ending yesterday
    # Build the 7 calendar days in MV local, from oldest to newest, up to (window_end_mv - 1 day)
    end_date = (window_end_mv - timedelta(days=1)).date()
    day_dates = [end_date - timedelta(days=delta) for delta in range(6, -1, -1)]
    day_counts = {d: 0 for d in day_dates}

    for log in arrival_logs:
        log_date = ensure_datetime(log.timestamp).astimezone(mv_tz).date()
        if log_date in day_counts:
            day_counts[log_date] += 1

    max_daily = max(day_counts.values()) if day_counts else 0
    # Include a sortable YYYY-MM-DD key so UIs can reliably order newest→oldest
    daily_trips = [
        {
            "day": d.strftime("%a"),  # Sun, Mon, ... (kept for compatibility)
            "date": d.strftime("%d %b"),  # 07 Nov
            "label": d.strftime("%b %d"),  # Nov 07 — uniform width for charts
            "date_key": d.strftime("%Y-%m-%d"),  # 2025-11-14
            "arrivals": cnt,
            "is_peak": cnt == max_daily and max_daily > 0,
        }
        for d, cnt in sorted(day_counts.items(), key=lambda x: x[0], reverse=True)
    ]

    # 8) Compose result
    # Display period ends on yesterday (last full day of data), not today
    display_end_mv = window_end_mv - timedelta(days=1)
    result = {
        "period": {
            "start": window_start_mv.strftime("%d %b %Y %H:%M"),
            "end": window_end_mv.strftime("%d %b %Y %H:%M"),
            # Display labels without leading zero in day (e.g., Nov 7)
            "start_display": f"{window_start_mv.strftime('%b')} {window_start_mv.day}",
            "end_display": f"{display_end_mv.strftime('%b')} {display_end_mv.day}",
        },
        "inactive": False,
        "message": None,
        "history": history_compact,
        "visited_islands_ranked": visited_islands_ranked,
        "most_visited_islands": most_visited_islands,
        "most_visited_count": most_visited_count if most_visited_islands else None,
        "active_time": format_duration(active_seconds),
        "active_time_seconds": int(active_seconds),
        "longest_trip": longest_trip,
        "activity_hours": activity_hours,
        "hourly_travel_seconds": hourly_travel_seconds,
        "daily_trips": daily_trips,
    }

    if int(active_seconds) == 0:
        result["inactive"] = True
        result["message"] = "Vessel was inactive in the last 7 days"
        # Trim fields that aren't meaningful when inactive
        result["history"] = []
        result["visited_islands_ranked"] = []
        result["most_visited_islands"] = []
        result["most_visited_count"] = None
        result["longest_trip"] = None
        result["activity_hours"] = []
        result["daily_trips"] = []

    return result

if __name__ == "__main__":
    # Example usage:
    port_id = 2  # Replace with actual port ID
    import pprint

    pprint.pprint(get_daily_port_stats(port_id))
