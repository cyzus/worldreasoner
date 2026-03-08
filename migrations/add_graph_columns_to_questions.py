import sqlite3
import argparse
import sys
from pathlib import Path

def migrate(db_path: str):
    """Add new graph builder columns to questions table."""
    db_file = Path(db_path)
    if not db_file.exists():
        print(f"Database not found at {db_path}")
        sys.exit(1)

    print(f"Connecting to database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get existing columns
    cursor.execute("PRAGMA table_info(questions)")
    columns = [col[1] for col in cursor.fetchall()]

    added = 0
    try:
        if "causal_explanation" not in columns:
            print("Adding causal_explanation column...")
            cursor.execute("ALTER TABLE questions ADD COLUMN causal_explanation TEXT")
            added += 1
            
        if "graph_built" not in columns:
            print("Adding graph_built column...")
            cursor.execute("ALTER TABLE questions ADD COLUMN graph_built BOOLEAN DEFAULT 0")
            added += 1
            
        if "graph_build_error" not in columns:
            print("Adding graph_build_error column...")
            cursor.execute("ALTER TABLE questions ADD COLUMN graph_build_error TEXT")
            added += 1

        if added > 0:
            conn.commit()
            print(f"Successfully added {added} columns to questions table.")
        else:
            print("All columns already exist. No migration needed.")

    except sqlite3.Error as e:
        conn.rollback()
        print(f"Error migrating database: {e}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add graph builder columns to questions table")
    parser.add_argument("--db", default="data/worldreasoner.db", help="Path to database")
    args = parser.parse_args()
    
    migrate(args.db)
