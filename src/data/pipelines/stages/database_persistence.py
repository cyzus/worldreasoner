"""Database persistence stage.

This stage saves pipeline outputs (articles, events, questions) to the database.
Acts as a thin wrapper around the Database class for pipeline integration.
"""

from typing import Any, List, Union, TYPE_CHECKING
from pydantic import BaseModel

from ..base import PipelineStage
from ....utils.config import DatabaseConfig
from ...models import Article, Event, Question

if TYPE_CHECKING:
    from ....utils.database import Database


class DatabasePersistenceConfig(BaseModel):
    """Configuration for database persistence."""
    batch_size: int = 100
    upsert: bool = True  # Update if exists (always True for SQLite INSERT OR REPLACE)
    db_path: str = "worldreasoner.db"  # Path to SQLite database


class DatabasePersistenceStage(PipelineStage[Any, Any]):
    """Persists data to database.
    
    Used in both pipelines to save results to SQLite database.
    Handles articles, events, and questions based on entity_type.
    """
    
    def __init__(
        self, 
        persistence_config: DatabasePersistenceConfig,
        entity_type: str,  # "article", "event", "question"
        db: "Database" = None  # Optional: pass existing Database instance
    ):
        """Initialize persistence stage.
        
        Args:
            persistence_config: Configuration for persistence behavior
            entity_type: Type of entities to persist ("article", "event", "question")
            db: Optional Database instance (creates new one if not provided)
        """
        super().__init__(
            name=f"DatabasePersistence_{entity_type}", 
            config=persistence_config
        )
        self.entity_type = entity_type
        self.batch_size = persistence_config.batch_size
        
        # Initialize or use provided database (lazy import to avoid circular dependency)
        if db:
            self.db = db
        else:
            from ....utils.database import Database
            self.db = Database(persistence_config.db_path)
    
    async def process(self, inputs: List[Any]) -> List[Any]:
        """Persist entities to database.
        
        Args:
            inputs: List of entities to persist (Article, Event, or Question objects)
            
        Returns:
            Same entities (unchanged, as IDs are already set)
        """
        if not inputs:
            return inputs
        
        # Dispatch to appropriate save method based on entity type
        if self.entity_type == "article":
            self._save_articles(inputs)
        elif self.entity_type == "event":
            self._save_events(inputs)
        elif self.entity_type == "question":
            self._save_questions(inputs)
        else:
            raise ValueError(
                f"Unknown entity_type '{self.entity_type}'. "
                f"Must be 'article', 'event', or 'question'"
            )
        
        return inputs
    
    def _save_articles(self, articles: List[Article]) -> int:
        """Save articles to database in batches.
        
        Args:
            articles: List of Article objects
            
        Returns:
            Number of articles saved
        """
        total_saved = 0
        
        # Process in batches
        for i in range(0, len(articles), self.batch_size):
            batch = articles[i:i + self.batch_size]
            saved = self.db.save_articles(batch)
            total_saved += saved
            
            print(f"  [DB] Saved {saved}/{len(batch)} articles (batch {i//self.batch_size + 1})")
        
        return total_saved
    
    def _save_events(self, events: List[Event]) -> int:
        """Save events to database in batches.
        
        Args:
            events: List of Event objects
            
        Returns:
            Number of events saved
        """
        total_saved = 0
        
        # Process in batches
        for i in range(0, len(events), self.batch_size):
            batch = events[i:i + self.batch_size]
            saved = self.db.save_events(batch)
            total_saved += saved
            
            print(f"  [DB] Saved {saved}/{len(batch)} events (batch {i//self.batch_size + 1})")
        
        return total_saved
    
    def _save_questions(self, questions: List[Question]) -> int:
        """Save questions to database in batches.
        
        Args:
            questions: List of Question objects
            
        Returns:
            Number of questions saved
        """
        total_saved = 0
        
        # Process in batches
        for i in range(0, len(questions), self.batch_size):
            batch = questions[i:i + self.batch_size]
            saved = self.db.save_questions(batch)
            total_saved += saved
            
            print(f"  [DB] Saved {saved}/{len(batch)} questions (batch {i//self.batch_size + 1})")
        
        return total_saved
