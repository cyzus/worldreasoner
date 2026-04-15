import json
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.database import GenericDatabase
from src.domain.models import Event, ReviewStatus

def import_annotation_results(db_path="experiment.db", json_file="scripts/annotation_ui/annotation_results.json"):
    if not os.path.exists(json_file):
        print(f"Error: {json_file} not found.")
        return

    db = GenericDatabase(db_path)
    
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    updated_count = 0
    for q in data:
        for e_data in q.get("events", []):
            event_id = e_data.get("id")
            status_str = e_data.get("current_status")
            reason = e_data.get("reject_reason")

            if not event_id or status_str == "pending":
                continue

            # Fetch event from DB
            event = db.get(Event, event_id)
            if not event:
                print(f"Warning: Event {event_id} not found in DB. Skipping.")
                continue

            # Map string to Enum
            try:
                new_status = ReviewStatus(status_str)
            except ValueError:
                print(f"Warning: Invalid status '{status_str}' for event {event_id}. Skipping.")
                continue
            
            # Update and save
            event.review_status = new_status
            if reason:
                event.review_note = f"Human Review: {reason}"
            
            db.update(event)
            updated_count += 1

    print(f"✅ Successfully updated {updated_count} events in the database.")

if __name__ == "__main__":
    db_name = sys.argv[1] if len(sys.argv) > 1 else "experiment.db"
    json_path = sys.argv[2] if len(sys.argv) > 2 else "scripts/annotation_ui/annotation_results.json"
    import_annotation_results(db_name, json_path)
