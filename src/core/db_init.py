"""Initialize and migrate database tables for all registered models.

This is the importable home for the logic that used to live in
``scripts/init_db.py``. The ``wr db init`` CLI command wraps ``init_and_migrate``.
"""

from typing import Callable, Optional

from src.core.database import GenericDatabase, _registry
from src.domain.models import *  # noqa: F401,F403 - import to register all models

try:
    from pydantic_core import PydanticUndefined
except ImportError:  # pragma: no cover - fallback if pydantic_core layout changes
    PydanticUndefined = object()


def init_and_migrate(
    db_path: str = "worldreasoner.db",
    log: Optional[Callable[[str], None]] = None,
) -> None:
    """Create missing tables and add any missing columns for registered models.

    Args:
        db_path: Path to the SQLite database.
        log: Optional callback for progress messages (defaults to ``print``).
    """
    emit = log or print
    emit(f"Initializing/Migrating database: {db_path}")
    db = GenericDatabase(db_path)

    # 1. Initialize tables (creates if not exist)
    try:
        count = db.initialize_all_tables()
        emit(f"Created {count} new tables (if they didn't exist).")
    except Exception as e:
        emit(f"Error initializing tables: {e}")
        # Continue to migration even if init fails (e.g. partial init)

    # 2. Auto-migrate: add missing columns for existing tables
    emit("\nChecking for schema updates (missing columns)...")
    migrated_count = 0

    for model in _registry.get_models():
        try:
            table_name = _registry.get_table_name(model)

            for field_name, field_info in model.model_fields.items():
                try:
                    python_type = db._get_python_type(field_info)
                    sql_type = db._map_to_sql_type(python_type)

                    # Handle default values for new columns, only if explicitly set
                    if (
                        field_info.default is not None
                        and field_info.default is not PydanticUndefined
                    ):
                        try:
                            default_val = db._serialize_value(
                                field_info.default, python_type
                            )
                            if isinstance(default_val, str):
                                default_val = f"'{default_val}'"
                            elif isinstance(default_val, bool):
                                default_val = 1 if default_val else 0
                            sql_type += f" DEFAULT {default_val}"
                        except Exception:
                            # If serialization fails (e.g. complex object), skip default
                            pass
                    elif python_type == "bool" and field_info.default is False:
                        sql_type += " DEFAULT 0"

                    added = db.ensure_column(model, field_name, sql_type)
                    if added:
                        emit(
                            f"  [MIGRATE] Table '{table_name}': "
                            f"Added column '{field_name}' ({sql_type})"
                        )
                        migrated_count += 1
                except ValueError:
                    # Model not registered properly or similar; skip
                    pass
                except Exception as e:
                    emit(
                        f"  [ERROR] Failed to check/add column '{field_name}' "
                        f"to '{table_name}': {e}"
                    )
        except Exception as e:
            emit(f"Error processing model {model}: {e}")

    if migrated_count == 0:
        emit("Schema is up to date.")
    else:
        emit(f"\nMigration complete. Added {migrated_count} missing columns.")

    # 3. Verify critical tables exist
    expected_tables = ["events", "articles", "questions", "event_outcome_impacts"]
    emit("\nVerifying tables...")
    try:
        with db._get_connection() as conn:
            cursor = conn.cursor()
            for table in expected_tables:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                if cursor.fetchone():
                    emit(f"  OK: {table}")
                else:
                    emit(f"  MISSING: {table}")
    except Exception as e:
        emit(f"Error verifying tables: {e}")
