"""Unified database layer for WorldReasoner.

This module provides the ONLY database interface for the project:

1. **GenericDatabase**: Low-level, type-safe interface for any Pydantic model
   - Automatic schema generation from model decorators
   - JSON serialization for complex types
   - Type-safe CRUD operations

2. **Database**: High-level wrapper with convenience methods
   - Article, Event, Question specific operations
   - Built on top of GenericDatabase
   - Use this for most application code

IMPORTANT: This is the single source of truth for database operations.
All models must use @register_model decorator for automatic schema creation.

Architecture:
    Models (@register_model) → GenericDatabase → SQLite
                                      ↑
                                   Database (wrapper)

Usage:
    # Low-level (for tools, direct operations)
    db = GenericDatabase('worldreasoner.db')
    db.save(Article, article_instance)
    
    # High-level (for application code)
    db = Database('worldreasoner.db')
    db.save_article(article_instance)
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
    """
    
    def __init__(self, db_path: str = "worldreasoner.db"):
        """Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
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
    
    def _serialize_value(self, value: Any, python_type: str) -> Any:
        """Serialize Python value for database storage."""
        if value is None:
            return None
        
        if python_type == 'datetime':
            return value.isoformat()
        elif python_type == 'bool':
            return 1 if value else 0
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
            Model instance or None if not found
        """
        table_name = _registry.get_table_name(model)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {table_name} WHERE id = ?", (id_value,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_model(model, dict(row))
    
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
            List of model instances
        """
        table_name = _registry.get_table_name(model)
        
        query = f"SELECT * FROM {table_name} WHERE 1=1"
        params = []
        
        # Add ID filter
        if ids:
            placeholders = ','.join('?' * len(ids))
            query += f" AND id IN ({placeholders})"
            params.extend(ids)
        
        # Add field filters
        if filters:
            for field_name, value in filters.items():
                query += f" AND {field_name} = ?"
                params.append(value)
        
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [self._row_to_model(model, dict(row)) for row in rows]
    
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


class Database:
    """Unified database interface for all WorldReasoner models.
    
    Provides convenient methods for each model type while using
    the generic database underneath.
    """
    
    def __init__(self, db_path: str = "worldreasoner.db"):
        """Initialize database.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db = GenericDatabase(db_path)
        self.db_path = db_path
        self._init_schema()
    
    def _init_schema(self):
        """Initialize database schema for all registered models."""
        # Import models to ensure they're registered
        from ..data.models import Article, Event, Question
        
        # Create tables for all registered models
        self.db.create_table(Article)
        self.db.create_table(Event)
        self.db.create_table(Question)
    
    # Article operations
    def save_article(self, article) -> bool:
        """Save or update an article."""
        from ..data.models import Article
        return self.db.save(Article, article)
    
    def save_articles(self, articles: List) -> int:
        """Save multiple articles."""
        from ..data.models import Article
        return self.db.save_many(Article, articles)
    
    def get_article(self, article_id: str):
        """Get article by ID."""
        from ..data.models import Article
        return self.db.get(Article, article_id)
    
    def get_articles(self, article_ids: Optional[List[str]] = None) -> List:
        """Get multiple articles."""
        from ..data.models import Article
        return self.db.get_many(Article, ids=article_ids)
    
    # Event operations
    def save_event(self, event) -> bool:
        """Save or update an event."""
        from ..data.models import Event
        return self.db.save(Event, event)
    
    def save_events(self, events: List) -> int:
        """Save multiple events."""
        from ..data.models import Event
        return self.db.save_many(Event, events)
    
    def get_event(self, event_id: str):
        """Get event by ID."""
        from ..data.models import Event
        return self.db.get(Event, event_id)
    
    def get_events(
        self,
        event_ids: Optional[List[str]] = None,
        domain: Optional[str] = None,
        status: Optional[str] = None
    ) -> List:
        """Get multiple events with optional filters."""
        from ..data.models import Event
        filters = {}
        if domain:
            filters['domain'] = domain
        if status:
            filters['status'] = status
        return self.db.get_many(Event, ids=event_ids, filters=filters)
    
    # Question operations
    def save_question(self, question) -> bool:
        """Save or update a question."""
        from ..data.models import Question
        return self.db.save(Question, question)
    
    def save_questions(self, questions: List) -> int:
        """Save multiple questions."""
        from ..data.models import Question
        return self.db.save_many(Question, questions)
    
    def get_question(self, question_id: str):
        """Get question by ID."""
        from ..data.models import Question
        return self.db.get(Question, question_id)
    
    def get_questions(
        self,
        question_ids: Optional[List[str]] = None,
        domain: Optional[str] = None
    ) -> List:
        """Get multiple questions with optional filters."""
        from ..data.models import Question
        filters = {}
        if domain:
            filters['domain'] = domain
        return self.db.get_many(Question, ids=question_ids, filters=filters)
    
    # Utility operations
    def clear_all(self):
        """Clear all data (for testing)."""
        from ..data.models import Article, Event, Question
        self.db.clear_all(Article)
        self.db.clear_all(Event)
        self.db.clear_all(Question)
    
    def get_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        from ..data.models import Article, Event, Question
        return {
            "articles": self.db.count(Article),
            "events": self.db.count(Event),
            "questions": self.db.count(Question)
        }
