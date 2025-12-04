# Code Redundancy Refactoring Plan

**Date**: 2025-11-27
**Status**: Proposed
**Total Estimated Effort**: 8-12 hours

## Executive Summary

This document outlines identified code redundancies in the WorldReasoner codebase and provides a phased refactoring plan. The analysis identified ~240+ lines of duplicate code across 10 categories, with the highest priority items offering significant maintainability improvements with minimal risk.

---

## High-Priority Redundancies

### 1. Duplicate ID Generation Logic
**Priority**: High
**Effort**: 1 hour
**Impact**: Eliminates 45 lines, creates single source of truth for entity IDs

**Current State**:
- `src/pipelines/stages/tools/article_collector.py:270-274` - `_generate_article_id()`
- `src/pipelines/stages/tools/event_identifier.py:175-180` - `_generate_event_id()`
- `src/pipelines/stages/tools/batch_event_identifier.py:240-245` - `_generate_event_id()`

**Pattern**:
```python
def _generate_*_id(self, domain: Domain, date: datetime, counter: int) -> str:
    date_str = date.strftime('%Y%m%d')
    suffix = uuid.uuid4().hex[:8]
    return f"{prefix}_{domain.value}_{date_str}_{counter+1:03d}_{suffix}"
```

**Proposed Solution**:

Create `src/utils/id_generator.py`:
```python
"""Unified ID generation utilities."""
import uuid
from datetime import datetime
from src.domain.models.event import Domain


def generate_entity_id(
    entity_type: str,
    domain: Domain,
    date: datetime,
    counter: int
) -> str:
    """
    Generate unique entity ID with consistent format.

    Args:
        entity_type: Entity prefix (e.g., "art", "evt", "qst")
        domain: Domain enum value
        date: Date to include in ID
        counter: Sequential counter (0-based, will be formatted as 1-based)

    Returns:
        Formatted ID: {entity_type}_{domain}_{YYYYMMDD}_{counter:03d}_{random}

    Example:
        >>> generate_entity_id("art", Domain.TECH, datetime(2024,1,1), 0)
        "art_tech_20240101_001_a1b2c3d4"
    """
    date_str = date.strftime('%Y%m%d')
    suffix = uuid.uuid4().hex[:8]
    return f"{entity_type}_{domain.value}_{date_str}_{counter+1:03d}_{suffix}"


def generate_article_id(domain: Domain, date: datetime, counter: int) -> str:
    """Generate article ID."""
    return generate_entity_id("art", domain, date, counter)


def generate_event_id(domain: Domain, date: datetime, counter: int) -> str:
    """Generate event ID."""
    return generate_entity_id("evt", domain, date, counter)


def generate_question_id(domain: Domain, date: datetime, counter: int) -> str:
    """Generate question ID."""
    return generate_entity_id("qst", domain, date, counter)
```

**Migration Steps**:
1. Create `src/utils/id_generator.py` with unified functions
2. Update `article_collector.py` to use `generate_article_id()`
3. Update `event_identifier.py` to use `generate_event_id()`
4. Update `batch_event_identifier.py` to use `generate_event_id()`
5. Run full test suite to verify ID generation still works
6. Remove old `_generate_*_id()` methods

**Testing**:
- Unit tests for ID format consistency
- Integration tests to ensure existing functionality unchanged
- Verify IDs are unique and properly formatted

---

## Medium-Priority Redundancies

### 2. Redundant Usage Tracking Initialization
**Priority**: Medium
**Effort**: 2 hours
**Impact**: Eliminates 30 lines, improves consistency

**Current State**:
- `src/pipelines/stages/article_collection.py:67`
- `src/pipelines/stages/event_identification.py:57`
- `src/pipelines/stages/evidence_collection.py:100`
- `src/pipelines/stages/causal_reasoning.py:82`
- `src/pipelines/stages/question_generation.py:48`

**Pattern**:
```python
# In __init__:
self.usage_tracker = UsageTracker()

# In process():
usage_metrics = self.base_agent.get_last_usage()
if usage_metrics:
    self.usage_tracker.add_usage(usage_metrics)
    log_usage(usage_metrics, context="StageName")

# At end:
if self.usage_tracker.total_calls > 0:
    self.usage_tracker.log_summary(context="StageName")
```

**Proposed Solution**:

Update `src/pipelines/base.py`:
```python
class PipelineStage(ABC, Generic[TInput, TOutput]):
    """Base class for pipeline stages with built-in usage tracking."""

    def __init__(
        self,
        name: str,
        config: Optional[BaseModel] = None,
        track_usage: bool = True
    ):
        self.name = name
        self.config = config
        self.track_usage = track_usage
        if track_usage:
            self._usage_tracker = UsageTracker()

    def track_agent_usage(self, agent) -> None:
        """Track usage from agent execution."""
        if not self.track_usage:
            return

        metrics = agent.get_last_usage()
        if metrics:
            self._usage_tracker.add_usage(metrics)
            log_usage(metrics, context=self.name)

    def finalize_usage_tracking(self) -> None:
        """Log final usage summary."""
        if self.track_usage and self._usage_tracker.total_calls > 0:
            self._usage_tracker.log_summary(context=self.name)
```

**Migration Steps**:
1. Update `PipelineStage` base class with tracking methods
2. Update each stage to call `self.track_agent_usage(agent)` after agent runs
3. Update each stage to call `self.finalize_usage_tracking()` at end
4. Remove manual `UsageTracker` initialization from stages
5. Run full test suite

---

### 3. Duplicate Enum Validation Logic
**Priority**: Medium
**Effort**: 1 hour
**Impact**: Eliminates 35 lines

**Current State**:
- `src/pipelines/stages/tools/article_collector.py:240-245`
- `src/pipelines/stages/tools/event_identifier.py:128-137`
- `src/pipelines/stages/tools/batch_event_identifier.py:204-213`

**Pattern**:
```python
try:
    domain_enum = Domain(domain.lower() if domain else "general")
except ValueError:
    print(f"Warning: Invalid domain '{domain}', using 'general'")
    domain_enum = Domain.GENERAL

try:
    event_type_enum = EventType(event_type.lower())
except ValueError:
    print(f"Warning: Invalid event_type '{event_type}', using 'indicator'")
    event_type_enum = EventType.INDICATOR
```

**Proposed Solution**:

Create `src/utils/enums.py`:
```python
"""Enum parsing utilities with safe fallbacks."""
from typing import Optional
from src.domain.models.event import Domain, EventType
from src.utils.logging import logger


def parse_domain(domain_str: Optional[str], default: Domain = Domain.GENERAL) -> Domain:
    """
    Parse domain string with fallback to default.

    Args:
        domain_str: Domain string to parse
        default: Default domain if parsing fails

    Returns:
        Parsed Domain enum or default
    """
    if not domain_str:
        return default

    try:
        return Domain(domain_str.lower())
    except ValueError:
        logger.warning(f"Invalid domain '{domain_str}', using '{default.value}'")
        return default


def parse_event_type(
    event_type_str: Optional[str],
    default: EventType = EventType.INDICATOR
) -> EventType:
    """
    Parse event type string with fallback to default.

    Args:
        event_type_str: Event type string to parse
        default: Default event type if parsing fails

    Returns:
        Parsed EventType enum or default
    """
    if not event_type_str:
        return default

    try:
        return EventType(event_type_str.lower())
    except ValueError:
        logger.warning(
            f"Invalid event_type '{event_type_str}', using '{default.value}'"
        )
        return default
```

**Migration Steps**:
1. Create `src/utils/enums.py` with parsing functions
2. Replace inline enum parsing in all affected files
3. Update to use `logger` instead of `print()`
4. Run full test suite

---

### 4. Duplicate Collector Pattern
**Priority**: Medium
**Effort**: 2-3 hours
**Impact**: Eliminates 50 lines, improves consistency

**Current State**:
- `src/pipelines/stages/tools/article_collector.py:181-189`
- `src/pipelines/stages/tools/event_identifier.py:155-163`
- `src/pipelines/stages/tools/batch_event_identifier.py:174-182`
- `src/pipelines/stages/tools/question_generator.py` (similar pattern)

**Pattern**:
```python
if self.collector is not None:
    self.collector.add(item)
    logger.debug(f"Added {item} to collector (total: {self.collector.count()})")
else:
    self.collected_items.append(item)
    logger.debug(f"Added {item} to internal list (total: {len(self.collected_items)})")
```

**Proposed Solution**:

Create `src/pipelines/stages/tools/base.py`:
```python
"""Base classes for pipeline tools."""
from typing import Any, Generic, TypeVar, Optional, List
from smolagents import Tool
from src.pipelines.stages.collectors import ResultCollector
from src.utils.logging import logger

T = TypeVar('T')


class CollectorAwareTool(Tool, Generic[T]):
    """
    Base class for tools that collect results.

    Provides unified interface for storing results in either:
    - External ResultCollector (preferred for pipeline integration)
    - Internal fallback list (for standalone use)
    """

    def __init__(self, collector: Optional[ResultCollector[T]] = None):
        super().__init__()
        self.collector = collector
        self._fallback_items: List[T] = []

    def store_result(self, item: T, context: str = "") -> None:
        """
        Store result using collector or fallback list.

        Args:
            item: Item to store
            context: Optional context for logging (e.g., "Article", "Event")
        """
        if self.collector is not None:
            self.collector.add(item)
            count = self.collector.count()
            logger.debug(f"{context}: Added to collector (total: {count})")
        else:
            self._fallback_items.append(item)
            count = len(self._fallback_items)
            logger.debug(f"{context}: Added to fallback list (total: {count})")

    def get_stored_count(self) -> int:
        """Get count of stored items."""
        if self.collector is not None:
            return self.collector.count()
        return len(self._fallback_items)

    def get_stored_items(self) -> List[T]:
        """Get all stored items (mainly for testing)."""
        if self.collector is not None:
            return self.collector.get_all()
        return self._fallback_items.copy()
```

**Migration Steps**:
1. Create `src/pipelines/stages/tools/base.py` with `CollectorAwareTool`
2. Update `ArticleCollectorTool` to inherit from `CollectorAwareTool[Article]`
3. Update `EventIdentifierTool` to inherit from `CollectorAwareTool[Event]`
4. Update `BatchEventIdentifierTool` to inherit from `CollectorAwareTool[Event]`
5. Update `QuestionGeneratorTool` to inherit from `CollectorAwareTool[Question]`
6. Replace inline collector logic with `self.store_result(item, context="EntityType")`
7. Remove `self.collected_items` initialization from tools
8. Run full test suite

---

### 5. Duplicate Datetime Parsing
**Priority**: Medium
**Effort**: 1 hour
**Impact**: Eliminates 20 lines

**Current State**:
- `src/pipelines/stages/tools/article_collector.py:175-178`
- `src/pipelines/stages/tools/event_identifier.py:117-123`
- `src/pipelines/stages/tools/batch_event_identifier.py:193-199`

**Pattern**:
```python
if published_date:
    try:
        pub_date = datetime.fromisoformat(published_date.replace('Z', '+00:00'))
    except:
        pub_date = datetime.now(timezone.utc)
else:
    pub_date = datetime.now(timezone.utc)
```

**Proposed Solution**:

Create `src/utils/date_utils.py`:
```python
"""Datetime utilities with safe parsing."""
from datetime import datetime, timezone
from typing import Optional
from src.utils.logging import logger


def parse_iso_datetime(
    date_str: Optional[str],
    fallback: Optional[datetime] = None
) -> datetime:
    """
    Parse ISO datetime string with timezone handling.

    Args:
        date_str: ISO format datetime string (may include 'Z' suffix)
        fallback: Fallback datetime if parsing fails (default: current UTC time)

    Returns:
        Parsed datetime or fallback

    Examples:
        >>> parse_iso_datetime("2024-01-01T12:00:00Z")
        datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        >>> parse_iso_datetime(None)
        datetime.now(timezone.utc)
    """
    if not date_str:
        return fallback or datetime.now(timezone.utc)

    try:
        # Handle 'Z' suffix by replacing with +00:00
        normalized = date_str.replace('Z', '+00:00')
        return datetime.fromisoformat(normalized)
    except (ValueError, AttributeError) as e:
        logger.warning(f"Failed to parse datetime '{date_str}': {e}")
        return fallback or datetime.now(timezone.utc)


def ensure_timezone_aware(dt: datetime) -> datetime:
    """
    Ensure datetime is timezone-aware (UTC if naive).

    Args:
        dt: Datetime to check

    Returns:
        Timezone-aware datetime (converted to UTC if naive)
    """
    if dt.tzinfo is None:
        logger.warning("Converting naive datetime to UTC")
        return dt.replace(tzinfo=timezone.utc)
    return dt
```

**Migration Steps**:
1. Create `src/utils/date_utils.py` with parsing functions
2. Update all affected tools to use `parse_iso_datetime()`
3. Run full test suite to verify datetime handling

---

## Low-Priority Items

### 6. Inconsistent Database Import Patterns
**Priority**: Low
**Effort**: 30 minutes
**Impact**: Code consistency

**Issue**: Some files use lazy imports, others use module-level imports for database classes.

**Recommendation**: Standardize on module-level imports for core dependencies:
```python
# At top of file
from src.core.database import GenericDatabase, Database
```

Use lazy imports only for optional dependencies or to break circular imports.

---

### 7. URL Normalization (Future Reusability)
**Priority**: Low
**Effort**: 1 hour
**Impact**: Enables reuse across URL-handling tools

**Current State**:
- `src/pipelines/stages/tools/article_collector.py:276-313` - Only place with URL normalization

**Recommendation**: Extract to `src/utils/url_utils.py` for future reuse in other tools that handle URLs.

---

### 8. Dead Code Audit
**Priority**: Low
**Effort**: 2-3 hours
**Impact**: Reduced maintenance burden

**Candidates for Review**:
- `src/pipelines/stages/tools/event_details.py` - Check if `EventDetailsTool` is actively used
- `src/pipelines/stages/tools/market_question_enhancer.py` - Check usage frequency
- Large tool files (e.g., `ArticleCollectorTool` at 331 lines) - Check for unused methods

**Recommended Approach**:
```bash
# Run coverage analysis
uv run pytest --cov=src --cov-report=html --cov-report=term-missing tests/

# Review coverage report to identify unused code
```

---

## Implementation Phases

### Phase 1: Quick Wins (2-3 hours)
**Goal**: Maximum impact, minimal risk

1. **ID Generation Utility** (1 hour)
   - Create `src/utils/id_generator.py`
   - Migrate 3 files
   - Test thoroughly

2. **Enum Parsing Utilities** (1 hour)
   - Create `src/utils/enums.py`
   - Migrate 3 files
   - Switch from `print()` to `logger`

3. **Datetime Parsing Utility** (1 hour)
   - Create `src/utils/date_utils.py`
   - Migrate 3 files
   - Test edge cases

**Success Criteria**:
- All tests pass
- ~100 lines of duplicate code eliminated
- No behavioral changes

---

### Phase 2: Medium Refactoring (3-4 hours)
**Goal**: Improve architectural consistency

4. **Collector-Aware Tool Base Class** (2-3 hours)
   - Create `src/pipelines/stages/tools/base.py`
   - Migrate 4+ tool classes
   - Update tests

5. **Standardize Agent Initialization** (1 hour)
   - Review agent creation patterns
   - Document best practices
   - Optionally add helper methods to base class

**Success Criteria**:
- Tool classes use unified base
- ~70 lines of duplicate code eliminated
- Consistent patterns across codebase

---

### Phase 3: Base Class Enhancement (2-3 hours)
**Goal**: Centralize common pipeline functionality

6. **Usage Tracking in PipelineStage** (2 hours)
   - Update `src/pipelines/base.py`
   - Migrate 5 stage classes
   - Update tests

7. **Pipeline Utility Functions** (1 hour)
   - Common filtering logic
   - Error handling patterns
   - Metric aggregation

**Success Criteria**:
- ~30 lines eliminated from each stage
- Usage tracking fully automated
- Cleaner stage implementations

---

### Phase 4: Cleanup (2-3 hours)
**Goal**: Remove technical debt

8. **Standardize Import Patterns** (30 min)
9. **Dead Code Removal** (2 hours)
10. **Documentation Updates** (30 min)

**Success Criteria**:
- No unused code in main branches
- AGENTS.md updated with new patterns
- Code coverage report clean

---

## Testing Strategy

### Unit Tests
- Test each new utility function independently
- Ensure backward compatibility with existing behavior
- Test edge cases (None values, invalid inputs, etc.)

### Integration Tests
- Run full test suite after each phase
- Verify pipeline outputs unchanged
- Check that ID generation maintains format

### Manual Testing
- Run question pipeline end-to-end
- Run evidence pipeline end-to-end
- Verify database schemas unchanged

### Regression Prevention
```bash
# Before starting
git checkout -b refactor/code-consolidation

# After each phase
uv run pytest tests/ -v
uv run pytest tests/integration/ -v -m integration

# Full validation
uv run pytest --cov=src --cov-report=term-missing tests/
```

---

## Risk Mitigation

### High-Risk Areas
1. **ID Generation Changes**: Could break existing database references
   - Mitigation: Extensive testing, verify format unchanged

2. **Collector Pattern Changes**: Core to pipeline functionality
   - Mitigation: Incremental migration, test each tool independently

3. **Base Class Changes**: Affects all stages
   - Mitigation: Make changes backward-compatible, use opt-in flags

### Rollback Plan
- Each phase is in separate commits
- Can cherry-pick successful phases
- Feature flags for base class changes

---

## Success Metrics

### Quantitative
- **Lines Eliminated**: Target 240+ lines of duplicate code
- **Files Consolidated**: 10+ files refactored
- **Utility Functions Created**: 8-10 new reusable utilities
- **Test Coverage**: Maintain or increase current coverage

### Qualitative
- Easier to maintain ID generation (single source of truth)
- Consistent patterns across all tools
- Reduced cognitive load for new developers
- Better adherence to DRY principle

---

## Timeline

**Optimistic**: 8 hours (1 focused day)
**Realistic**: 12 hours (1.5 days with testing)
**Conservative**: 16 hours (2 days with comprehensive testing)

**Recommended Approach**: Execute Phase 1 first, evaluate results, then decide on Phases 2-4 based on value delivered.

---

## Appendix: File Reference

### Files to Create
- `src/utils/id_generator.py`
- `src/utils/enums.py`
- `src/utils/date_utils.py`
- `src/utils/url_utils.py` (optional)
- `src/pipelines/stages/tools/base.py`

### Files to Modify
**High Priority**:
- `src/pipelines/stages/tools/article_collector.py`
- `src/pipelines/stages/tools/event_identifier.py`
- `src/pipelines/stages/tools/batch_event_identifier.py`

**Medium Priority**:
- `src/pipelines/stages/article_collection.py`
- `src/pipelines/stages/event_identification.py`
- `src/pipelines/stages/evidence_collection.py`
- `src/pipelines/stages/causal_reasoning.py`
- `src/pipelines/stages/question_generation.py`
- `src/pipelines/stages/tools/question_generator.py`

**Low Priority**:
- `src/pipelines/base.py`
- Various other tools and utilities

---

## Notes

- This plan prioritizes **safety and incrementality** over speed
- Each phase can be executed independently
- All changes maintain backward compatibility
- Focus on eliminating true duplication, not premature abstraction
- Follow AGENTS.md conventions throughout refactoring

---

**Document Status**: Ready for Review
**Next Steps**: Approve plan and execute Phase 1
