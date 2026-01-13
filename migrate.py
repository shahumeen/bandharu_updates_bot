#!/usr/bin/env python3
"""
Migration script to populate SQLite database from JSON files in the 'data migrate' folder.
Creates all necessary tables and populates them with data.
Keeps PortLogNotification table empty as requested.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from models import (
    db,
    Port,
    User,
    Vessel,
    PortSubscription,
    VesselSubscription,
    PortLog,
    PortLogNotification,
)


def load_json_file(filename):
    """Load JSON data from file in the 'data migrate' folder."""
    filepath = Path(__file__).parent / "data migrate" / filename
    if not filepath.exists():
        print(f"Warning: {filepath} not found")
        return {}
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def migrate_ports():
    """Migrate Port data from port.json"""
    print("Migrating Ports...")
    data = load_json_file("port.json")
    
    ports = data.get("port", [])
    for port_data in ports:
        Port.get_or_create(
            id=port_data["id"],
            defaults={"name": port_data["name"]}
        )
    
    print(f"  ✓ Migrated {len(ports)} ports")


def migrate_vessels():
    """Migrate Vessel data from vessel.json"""
    print("Migrating Vessels...")
    data = load_json_file("vessel.json")
    
    vessels = data.get("vessel", [])
    for vessel_data in vessels:
        last_port_id = vessel_data.get("last_port_id")
        
        # Only set last_port if it exists in the database
        last_port = None
        if last_port_id:
            try:
                last_port = Port.get_by_id(last_port_id)
            except:
                pass
        
        Vessel.get_or_create(
            id=vessel_data["id"],
            defaults={
                "name": vessel_data["name"],
                "vessel_type": vessel_data.get("vessel_type"),
                "contact": vessel_data.get("contact"),
                "last_port": last_port,
                "last_port_log_id": vessel_data.get("last_port_log_id"),
            }
        )
    
    print(f"  ✓ Migrated {len(vessels)} vessels")


def migrate_users():
    """Migrate User data from user.json"""
    print("Migrating Users...")
    data = load_json_file("user.json")
    
    users = data.get("user", [])
    for user_data in users:
        main_port_id = user_data.get("main_port_id")
        main_port = None
        
        # Only set main_port if it exists in the database
        if main_port_id:
            try:
                main_port = Port.get_by_id(main_port_id)
            except:
                pass
        
        # Parse date_joined if it's a string
        date_joined = user_data.get("date_joined")
        if isinstance(date_joined, str):
            try:
                date_joined = datetime.fromisoformat(date_joined.replace('Z', '+00:00'))
            except:
                date_joined = datetime.now()
        
        User.get_or_create(
            chat_id=user_data["chat_id"],
            defaults={
                "chat_type": user_data["chat_type"],
                "username": user_data.get("username"),
                "first_name": user_data["first_name"],
                "last_name": user_data.get("last_name"),
                "date_joined": date_joined,
                "main_port": main_port,
                "notify_on_departure": user_data.get("notify_on_departure", True),
            }
        )
    
    print(f"  ✓ Migrated {len(users)} users")


def migrate_port_subscriptions():
    """Migrate PortSubscription data from portsubscription.json"""
    print("Migrating Port Subscriptions...")
    data = load_json_file("portsubscription.json")
    
    subscriptions = data.get("portsubscription", [])
    created_count = 0
    
    for sub_data in subscriptions:
        user_id = sub_data["user_id"]
        port_id = sub_data["port_id"]
        
        try:
            user = User.get_by_id(user_id)
            port = Port.get_by_id(port_id)
            
            PortSubscription.get_or_create(
                user=user,
                port=port
            )
            created_count += 1
        except:
            # Skip if user or port doesn't exist
            pass
    
    print(f"  ✓ Migrated {created_count} port subscriptions")


def migrate_vessel_subscriptions():
    """Migrate VesselSubscription data from vesselsubscription.json"""
    print("Migrating Vessel Subscriptions...")
    data = load_json_file("vesselsubscription.json")
    
    subscriptions = data.get("vesselsubscription", [])
    created_count = 0
    
    for sub_data in subscriptions:
        user_id = sub_data["user_id"]
        vessel_id = sub_data["vessel_id"]
        
        try:
            user = User.get_by_id(user_id)
            vessel = Vessel.get_by_id(vessel_id)
            
            VesselSubscription.get_or_create(
                user=user,
                vessel=vessel
            )
            created_count += 1
        except:
            # Skip if user or vessel doesn't exist
            pass
    
    print(f"  ✓ Migrated {created_count} vessel subscriptions")


def migrate_portlogs():
    """Migrate PortLog data from portlog.json using batch inserts"""
    print("Migrating Port Logs...")
    data = load_json_file("portlog.json")
    
    portlogs = data.get("portlog", [])
    batch_size = 1000
    created_count = 0
    skipped_count = 0
    
    # Prepare batch of records
    batch = []
    
    for log_data in portlogs:
        try:
            vessel_id = log_data["vessel_id"]
            port_id = log_data["port_id"]
            
            # Verify both vessel and port exist
            vessel = Vessel.get_by_id(vessel_id)
            port = Port.get_by_id(port_id)
            
            # Parse timestamp if it's a string
            timestamp = log_data.get("timestamp")
            if isinstance(timestamp, str):
                try:
                    timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except:
                    timestamp = datetime.now()
            
            # Create PortLog object (not saved yet)
            port_log = PortLog(
                timestamp=timestamp,
                vessel=vessel,
                port=port,
                event=log_data["event"],
                notified=log_data.get("notified", False),
            )
            batch.append(port_log)
            
            # Insert batch when it reaches batch_size
            if len(batch) >= batch_size:
                PortLog.bulk_create(batch, batch_size=batch_size)
                created_count += len(batch)
                print(f"  ✓ Inserted {created_count} port logs so far...")
                batch = []
                
        except Exception as e:
            # Skip if vessel or port doesn't exist
            skipped_count += 1
    
    # Insert remaining records
    if batch:
        PortLog.bulk_create(batch, batch_size=batch_size)
        created_count += len(batch)
    
    print(f"  ✓ Migrated {created_count} port logs (skipped {skipped_count})")


def create_tables():
    """Create all necessary tables."""
    print("Creating database tables...")
    db.create_tables([
        Port,
        User,
        Vessel,
        PortSubscription,
        VesselSubscription,
        PortLog,
        PortLogNotification,
    ])
    print("  ✓ Database tables created")


def main():
    """Run the complete migration."""
    print("\n" + "="*50)
    print("STARTING DATABASE MIGRATION")
    print("="*50 + "\n")
    
    try:
        # Create tables first
        create_tables()
        
        # Migrate data in order of dependencies
        migrate_ports()
        migrate_vessels()
        migrate_users()
        migrate_port_subscriptions()
        migrate_vessel_subscriptions()
        migrate_portlogs()
        
        # PortLogNotification table is kept empty as requested
        print("\nMigration Notifications:")
        print("  ℹ PortLogNotification table created but left empty (as requested)")
        
        print("\n" + "="*50)
        print("✓ MIGRATION COMPLETED SUCCESSFULLY")
        print("="*50 + "\n")
        
    except Exception as e:
        print(f"\n✗ MIGRATION FAILED: {e}")
        raise


if __name__ == "__main__":
    main()
