"""Unified database layer for WorldReasoner.

This module provides the database interface for the project:

**GenericDatabase**: Type-safe interface for any Pydantic model
   - Automatic schema generation from @register_model decorators
   - JSON serialization for complex types
   - Type-safe CRUD operations
   - Batch operations
   - Temporal filtering support

IMPORTANT: This is the single source of truth for database operations.
All models must use @register_model decorator for automatic schema creation.

Architecture:
    Models (@register_model) → GenericDatabase → SQLite

Usage:
    from src.core.database import GenericDatabase
    from src.domain.models import Article
    
    # Create database instance
    db = GenericDatabase('worldreasoner.db')
    
    # Ensure schema is initialized
    db.create_table(Article)
    
    # CRUD operations
    db.save(Article, article_instance)
    article = db.get(Article, article_id)
    articles = db.get_many(Article, filters={'domain': 'tech'})
    db.delete(Article, article_id)
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, TypeVar, Generic, Type, get_args, get_origin
from contextlib import contextmanager

from pydantic import BaseModel


T = TypeVar('T', bound=BaseModel)


class ModelRegistry:
    """Registry mapping Pydantic models to their database configurations."""
    
    def __init__(self):
        self._registry: Dict[Type[BaseModel], Dict[str, Any]] = {}
    
    def register(
        self,
        model: Type[BaseModel],
        table_name: str,
        indexes: Optional[List[str]] = None
    ):
        """Register a model with its database configuration.
        
        Args:
            model: Pydantic model class
            table_name: Name of database table
            indexes: Optional list of field names to index
        """
        self._registry[model] = {
            'table_name': table_name,
            'indexes': indexes or []
        }
    
    def get_table_name(self, model: Type[BaseModel]) -> str:
        """Get table name for a model."""
        config = self._registry.get(model)
        if not config:
            raise ValueError(f"Model {model.__name__} not registered")
        return config['table_name']
    
    def get_indexes(self, model: Type[BaseModel]) -> List[str]:
        """Get index fields for a model."""
        config = self._registry.get(model)
        if not config:
            return []
        return config['indexes']
    
    def is_registered(self, model: Type[BaseModel]) -> bool:
        """Check if model is registered."""
        return model in self._registry

    def get_models(self) -> List[Type[BaseModel]]:
        """Return all registered Pydantic model classes."""
        return list(self._registry.keys())


# Global registry instance
_registry = ModelRegistry()


def register_model(
    table_name: str,
    indexes: Optional[List[str]] = None
):
    """Decorator to register a Pydantic model for database storage.
    
    Args:
        table_name: Name of database table
        indexes: Optional list of field names to index
    
    Example:
        @register_model('articles', indexes=['domain', 'source'])
        class Article(BaseModel):
            ...
    """
    def decorator(cls: Type[BaseModel]) -> Type[BaseModel]:
        _registry.register(cls, table_name, indexes)
        return cls
    return decorator


class GenericDatabase(Generic[T]):
    """Generic type-safe database interface for Pydantic models.

    Automatically handles:
    - Schema creation from Pydantic model fields
    - Type conversion (Python <-> SQLite)
    - JSON serialization for complex types
    - CRUD operations
    - Batch operations
    - Temporal filtering (when cutoff_date is provided)
    """

    def __init__(self, db_path: str = "worldreasoner.db", cutoff_date: Optional[datetime] = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
            cutoff_date: Optional cutoff date for temporal filtering (timezone-aware).
                        If provided, Articles and Events will be automatically filtered.
                        If not provided, checks for active TemporalContext.

        Raises:
            ValueError: If cutoff_date is not timezone-aware
        """
        self.db_path = Path(db_path)
        self.cutoff_date = cutoff_date

        # Create temporal gateway if cutoff provided or context active
        if cutoff_date is not None:
            if cutoff_date.tzinfo is None:
                raise ValueError("cutoff_date must be timezone-aware (use datetime.now(timezone.utc))")
            from .temporal_gateway import TemporalGateway
            self.gateway = TemporalGateway(cutoff_date)
        else:
            # Check for active TemporalContext
            from .temporal_gateway import TemporalContext
            context_cutoff = TemporalContext.get_current_cutoff()
            if context_cutoff is not None:
                from .temporal_gateway import TemporalGateway
                self.gateway = TemporalGateway(context_cutoff)
                self.cutoff_date = context_cutoff
            else:
                self.gateway = None

        self._ensure_db_exists()
    
    def _ensure_db_exists(self):
        """Create database file if it doesn't exist."""
        if not self.db_path.exists():
            self.db_path.touch()
    
    @contextmanager
    def _get_connection(self):
        """Get database connection context manager."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _get_python_type(self, field_info) -> str:
        """Map Pydantic field to Python type string."""
        from enum import Enum
        
        annotation = field_info.annotation
        
        # Handle Optional types
        origin = get_origin(annotation)
        if origin is not None:
            args = get_args(annotation)
            if type(None) in args:
                # It's Optional[X], get the non-None type
                annotation = next(arg for arg in args if arg is not type(None))
        
        # Map to basic types
        if annotation in (str, int, float, bool):
            return annotation.__name__
        elif annotation == datetime:
            return 'datetime'
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return 'model'
        elif isinstance(annotation, type) and issubclass(annotation, Enum):
            return 'enum'
        else:
            # Complex types: list, dict, etc. -> JSON
            return 'json'
    
    def _map_to_sql_type(self, python_type: str) -> str:
        """Map Python type to SQLite type."""
        mapping = {
            'str': 'TEXT',
            'int': 'INTEGER',
            'float': 'REAL',
            'bool': 'INTEGER',
            'datetime': 'TEXT',
            'model': 'TEXT',  # Store as JSON
            'json': 'TEXT'
        }
        return mapping.get(python_type, 'TEXT')
    
    def _should_serialize(self, python_type: str) -> bool:
        """Check if value needs JSON serialization."""
        return python_type in ('json', 'model')
    
    def create_table(self, model: Type[T]):
        """Create table for a Pydantic model if it doesn't exist.
        
        Args:
            model: Pydantic model class
        """
        if not _registry.is_registered(model):
            raise ValueError(f"Model {model.__name__} not registered. Use @register_model decorator.")
        
        table_name = _registry.get_table_name(model)
        
        # Analyze model fields
        columns = []
        for field_name, field_info in model.model_fields.items():
            python_type = self._get_python_type(field_info)
            sql_type = self._map_to_sql_type(python_type)
            
            # Build column definition
            col_def = f"{field_name} {sql_type}"
            
            # Handle primary key (assume 'id' field)
            if field_name == 'id':
                col_def += " PRIMARY KEY"
            
            # Handle required fields
            if field_info.is_required() and field_name != 'id':
                col_def += " NOT NULL"
            
            columns.append(col_def)
        
        # Add audit columns only if they don't exist in the model
        if 'created_at' not in model.model_fields:
            columns.append("created_at TEXT DEFAULT CURRENT_TIMESTAMP")
        if 'updated_at' not in model.model_fields:
            columns.append("updated_at TEXT DEFAULT CURRENT_TIMESTAMP")
        
        # Create table
        with self._get_connection() as conn:
            cursor = conn.cursor()
            create_sql = f"""
                CREATE TABLE IF NOT EXISTS {table_name} (
                    {', '.join(columns)}
                )
            """
            cursor.execute(create_sql)
            
            # Create indexes
            for index_field in _registry.get_indexes(model):
                index_name = f"idx_{table_name}_{index_field}"
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS {index_name}
                    ON {table_name}({index_field})
                """)
            
            conn.commit()

    def initialize_all_tables(self) -> int:
        """Create tables for all registered models.

        Returns:
            Number of tables ensured/created.
        """
        count = 0
        for model in _registry.get_models():
            self.create_table(model)
            count += 1
        return count
    
    def _serialize_value(self, value: Any, python_type: str) -> Any:
        """Serialize Python value for database storage."""
        from enum import Enum
        
        if value is None:
            return None
        
        if python_type == 'datetime':
            return value.isoformat()
        elif python_type == 'bool':
            return 1 if value else 0
        elif python_type == 'enum':
            # For Enums, store the value (not JSON-encoded)
            return value.value if isinstance(value, Enum) else value
        elif python_type in ('json', 'model'):
            # Handle Pydantic models and complex types
            if isinstance(value, BaseModel):
                return json.dumps(value.model_dump())
            else:
                return json.dumps(value)
        else:
            return value
    
    def _deserialize_value(self, value: Any, python_type: str, field_info) -> Any:
        """Deserialize database value to Python type."""
        if value is None:
            # If field has a default_factory (e.g., list, dict), use it instead of None
            if field_info.default_factory:
                return field_info.default_factory()
            return None
        
        if python_type == 'datetime':
            return datetime.fromisoformat(value)
        elif python_type == 'bool':
            return bool(value)
        elif python_type == 'enum':
            # For Enums, get the enum class and construct from value
            annotation = field_info.annotation
            # Handle Optional
            origin = get_origin(annotation)
            if origin is not None:
                args = get_args(annotation)
                annotation = next(arg for arg in args if arg is not type(None))
            # Handle both plain string values and JSON-encoded values from old data
            if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
                value = json.loads(value)
            return annotation(value)
        elif python_type == 'json':
            return json.loads(value) if value else None
        elif python_type == 'model':
            # Reconstruct Pydantic model
            data = json.loads(value) if value else {}
            annotation = field_info.annotation
            # Handle Optional
            origin = get_origin(annotation)
            if origin is not None:
                args = get_args(annotation)
                annotation = next(arg for arg in args if arg is not type(None))
            return annotation(**data) if data else None
        else:
            return value
    
    def save(self, model: Type[T], instance: T) -> bool:
        """Save or update a model instance.
        
        Args:
            model: Pydantic model class
            instance: Model instance to save
            
        Returns:
            True if successful
        """
        table_name = _registry.get_table_name(model)
        
        # Extract field values
        data = instance.model_dump()
        field_names = list(model.model_fields.keys())
        
        # Serialize values
        serialized_values = []
        for field_name in field_names:
            field_info = model.model_fields[field_name]
            python_type = self._get_python_type(field_info)
            value = data.get(field_name)
            serialized_values.append(self._serialize_value(value, python_type))
        
        # Build SQL
        placeholders = ', '.join(['?'] * len(field_names))
        columns = ', '.join(field_names)
        
        # Add updated_at if the model doesn't have it
        if 'updated_at' not in model.model_fields:
            columns += ', updated_at'
            placeholders += ', ?'
            serialized_values.append(datetime.now().isoformat())
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                INSERT OR REPLACE INTO {table_name}
                ({columns})
                VALUES ({placeholders})
            """, serialized_values)
            conn.commit()
            return True
    
    def save_many(self, model: Type[T], instances: List[T]) -> int:
        """Save multiple instances in batch.
        
        Args:
            model: Pydantic model class
            instances: List of instances to save
            
        Returns:
            Number of instances saved
        """
        count = 0
        for instance in instances:
            if self.save(model, instance):
                count += 1
        return count
    
    def get(self, model: Type[T], id_value: str) -> Optional[T]:
        """Retrieve a model instance by ID.

        Args:
            model: Pydantic model class
            id_value: ID value to retrieve

        Returns:
            Model instance or None if not found or temporally inaccessible
        """
        table_name = _registry.get_table_name(model)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {table_name} WHERE id = ?", (id_value,))
            row = cursor.fetchone()

            if not row:
                return None

            instance = self._row_to_model(model, dict(row))

            # Apply temporal filtering if gateway exists
            if self.gateway is not None:
                from ..domain.models import Article, Event

                if model == Article:
                    if not self.gateway.is_article_accessible(instance):
                        return None
                elif model == Event:
                    if not self.gateway.is_event_accessible(instance):
                        return None

            return instance
    
    def get_many(
        self,
        model: Type[T],
        ids: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[T]:
        """Retrieve multiple model instances.

        Args:
            model: Pydantic model class
            ids: Optional list of specific IDs to retrieve
            filters: Optional dict of field:value filters

        Returns:
            List of model instances (temporally filtered if gateway active)
        """
        from ..domain.models import Article, Event

        table_name = _registry.get_table_name(model)
        filters = filters or {}

        query = f"SELECT * FROM {table_name} WHERE 1=1"
        params = []

        # Add ID filter
        if ids:
            placeholders = ','.join('?' * len(ids))
            query += f" AND id IN ({placeholders})"
            params.extend(ids)

        # Add temporal filter at SQL level (performance optimization)
        # Note: Uses < (strictly before) not <= to exclude items at cutoff
        if self.gateway is not None:
            if model == Article:
                query += " AND published_date < ?"
                params.append(self.cutoff_date.isoformat())
            elif model == Event:
                query += " AND occurred_date < ?"
                params.append(self.cutoff_date.isoformat())

        # Add field filters
        for field_name, value in filters.items():
            query += f" AND {field_name} = ?"
            params.append(value)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

            instances = [self._row_to_model(model, dict(row)) for row in rows]

        # Apply Python-level filtering for safety (catches None dates, etc.)
        if self.gateway is not None:
            if model == Article:
                instances = self.gateway.filter_articles(instances)
            elif model == Event:
                instances = self.gateway.filter_events(instances)

        return instances
    
    def delete(self, model: Type[T], id_value: str) -> bool:
        """Delete a model instance by ID.
        
        Args:
            model: Pydantic model class
            id_value: ID of instance to delete
            
        Returns:
            True if deleted, False if not found
        """
        table_name = _registry.get_table_name(model)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {table_name} WHERE id = ?", (id_value,))
            conn.commit()
            return cursor.rowcount > 0
    
    def count(self, model: Type[T], filters: Optional[Dict[str, Any]] = None) -> int:
        """Count instances of a model.
        
        Args:
            model: Pydantic model class
            filters: Optional dict of field:value filters
            
        Returns:
            Count of instances
        """
        table_name = _registry.get_table_name(model)
        
        query = f"SELECT COUNT(*) FROM {table_name} WHERE 1=1"
        params = []
        
        if filters:
            for field_name, value in filters.items():
                query += f" AND {field_name} = ?"
                params.append(value)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()[0]
    
    def _row_to_model(self, model: Type[T], row: Dict[str, Any]) -> T:
        """Convert database row to model instance.
        
        Args:
            model: Pydantic model class
            row: Database row as dict
            
        Returns:
            Model instance
        """
        # Deserialize each field
        data = {}
        for field_name, field_info in model.model_fields.items():
            if field_name in row:
                python_type = self._get_python_type(field_info)
                value = row[field_name]
                data[field_name] = self._deserialize_value(value, python_type, field_info)
        
        return model(**data)
    
    def clear_all(self, model: Type[T]):
        """Clear all data for a model (for testing).
        
        Args:
            model: Pydantic model class
        """
        table_name = _registry.get_table_name(model)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM {table_name}")
            conn.commit()
