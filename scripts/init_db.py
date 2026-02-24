"""Initialize and migrate database tables for all registered models."""
import sys
import os

# Add project root to path
sys.path.insert(0, os.getcwd())

from src.core.database import GenericDatabase, _registry
from src.domain.models import *  # Import all models to register them
try:
    from pydantic_core import PydanticUndefined
except ImportError:
    PydanticUndefined = object()

def init_db(db_path: str = "worldreasoner.db"):
    print(f"Initializing/Migrating database: {db_path}")
    db = GenericDatabase(db_path)
    
    # 1. Initialize tables (creates if not exist)
    try:
        count = db.initialize_all_tables()
        print(f"Created {count} new tables (if they didn't exist).")
    except Exception as e:
        print(f"Error initializing tables: {e}")
        # Continue to migration even if init fails (e.g. partial init)

    # 2. Auto-migrate: specific logic to add missing columns for existing tables
    print("\nChecking for schema updates (missing columns)...")
    migrated_count = 0
    
    for model in _registry.get_models():
        try:
            table_name = _registry.get_table_name(model)
            
            # Check each field in the model
            for field_name, field_info in model.model_fields.items():
                try:
                    # determine SQL type
                    python_type = db._get_python_type(field_info)
                    sql_type = db._map_to_sql_type(python_type)
                    
                    # Handle default values for new columns
                    # Only if default is explicitly set (not PydanticUndefined)
                    if field_info.default is not None and field_info.default is not PydanticUndefined:
                        # Convert default to SQL-compatible string
                        try:
                            default_val = db._serialize_value(field_info.default, python_type)
                            if isinstance(default_val, str):
                                default_val = f"'{default_val}'"
                            elif isinstance(default_val, bool):
                                default_val = 1 if default_val else 0
                            
                            # Add DEFAULT clause
                            sql_type += f" DEFAULT {default_val}"
                        except Exception:
                            # If serialization fails (e.g. complex object), skip default
                            pass
                            
                    elif python_type == "bool" and field_info.default is False:
                         # Special case for boolean defaulting to specific value
                         sql_type += " DEFAULT 0"
                    
                    # ensure_column checks if it exists before adding
                    added = db.ensure_column(model, field_name, sql_type)
                    if added:
                        print(f"  [MIGRATE] Table '{table_name}': Added column '{field_name}' ({sql_type})")
                        migrated_count += 1
                except ValueError:
                    # Can happen if model not registered properly or other issues
                    pass
                except Exception as e:
                    print(f"  [ERROR] Failed to check/add column '{field_name}' to '{table_name}': {e}")
        except Exception as e:
            print(f"Error processing model {model}: {e}")
                
    if migrated_count == 0:
        print("Schema is up to date.")
    else:
        print(f"\nMigration complete. Added {migrated_count} missing columns.")

    # 3. Verify critical tables exist
    expected_tables = ["events", "articles", "questions", "event_outcome_impacts"]
    print("\nVerifying tables...")
    try:
        with db._get_connection() as conn:
            cursor = conn.cursor()
            for table in expected_tables:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                if cursor.fetchone():
                    print(f"  OK: {table}")
                else:
                    print(f"  MISSING: {table}")
    except Exception as e:
        print(f"Error verifying tables: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Initialize/migrate database")
    parser.add_argument("--db", default="worldreasoner.db", help="Database path")
    args = parser.parse_args()
    init_db(args.db)
