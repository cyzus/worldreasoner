"""Prompts for question generation stage."""

from datetime import datetime
from typing import List, Optional
from src.domain.models import Event
from .base import ContextualPromptGenerator, PromptTemplate


class QuestionGenerationPrompts(ContextualPromptGenerator[Event]):
    """Prompts for the question generation stage."""
    
    # Template for formatting individual events
    EVENT_TEMPLATE = PromptTemplate(
        template="""
Event {idx} (ID: {event_id}){status_note}:
- Title: {title}
- Description: {description}
- Date: {event_date}
- Domain: {domain}
- Confidence: {confidence}
""",
        required_vars=["idx", "event_id", "title", "description", "event_date", "domain", "confidence"],
        optional_vars={"status_note": ""}
    )
    
    # Template for GROUND TRUTH mode (past events only)
    GENERATION_TEMPLATE_GROUND_TRUTH = PromptTemplate(
        template="""Generate {max_questions} forecast questions from PAST events.{domain_filter}

{events_text}

═══════════════════════════════════════════════════════════════════════
GROUND TRUTH MODE - Past Events with Known Outcomes
═══════════════════════════════════════════════════════════════════════

CRITICAL RULES:
1. Today: {current_date} → resolution_date MUST be ≤ {current_date}
2. ONLY use WELL-ESTABLISHED events marked "(PAST EVENT)"
3. Questions use FUTURE TENSE: "Will X happen by DATE?" (NOT "Did X happen?")
4. ground_truth = VERIFIED FACT from the past (NEVER a future date or speculation)
5. Use natural deadlines: "by end of Q4 2024" NOT "by Oct 27, 2024"

⚠️ GROUND TRUTH VALIDATION:
- ground_truth must be a DEFINITIVE PAST OUTCOME (e.g., "YES", "NO", "Apple", "500000")
- ground_truth CANNOT be a future date (e.g., "November 17 2025" is INVALID)
- If outcome is unknown/unverified, SKIP this event

DISTRIBUTION TRACKER (Track as you generate):
Generate EXACTLY in this order:
1. Boolean #1 (answer: YES/TRUE)
2. Boolean #2 (answer: NO/FALSE)
3. MCQ #1
4. MCQ #2
5. Quantity #1
6. Quantity #2
7. Timeframe #1
8. Timeframe #2
... continue pattern to {max_questions} questions

⚠️ CRITICAL: Alternate Boolean answers YES/NO/YES/NO to avoid bias!

QUESTION TYPES & EXAMPLES:

Boolean: "Will Bitcoin exceed $100K by Dec 31, 2024?" (specific threshold + deadline)
MCQ: "Who will win 2024 election: Trump, Harris, or Other?" (3-5 options + "Other")
Quantity: "Will Tesla deliver over 500K vehicles in Q4 2024?" (numerical threshold)
Timeframe: "When will Apple announce iPhone 15: Q3 2024, Q4 2024, or 2025+?" (date ranges)

QUALITY STANDARDS:
✓ Specific, measurable criteria  ✗ Vague ("Will AI improve?")
✓ Clear resolution source         ✗ Subjective ("Will movie be good?")
✓ Natural deadlines (end of Q4)   ✗ Arbitrary dates (Oct 27 at 3pm)
✓ Verifiable outcomes              ✗ Unprovable claims

Use {tool_name} to save each question. Return brief summary when done.""",
        required_vars=["num_events", "events_text", "max_questions", "current_date", "min_resolution_date"],
        optional_vars={
            "domain_filter": "",
            "tool_name": "question_generator"
        }
    )

    # Template for FUTURE events mode (predictions only)
    GENERATION_TEMPLATE_FUTURE = PromptTemplate(
        template="""Generate {max_questions} forecast questions about FUTURE events.{domain_filter}

{events_text}

═══════════════════════════════════════════════════════════════════════
FUTURE PREDICTION MODE - Unknown Outcomes
═══════════════════════════════════════════════════════════════════════

CRITICAL RULES:
1. Today: {current_date} → resolution_date MUST be > {current_date}
2. SKIP events marked "(PAST EVENT)"
3. NO ground_truth (outcomes unknown)
4. Resolution dates: 1-12 months in future

DISTRIBUTION TRACKER (Track as you generate):
Generate EXACTLY in this order:
1. Boolean #1 (predict: likely YES)
2. Boolean #2 (predict: likely NO)
3. MCQ #1
4. MCQ #2
5. Quantity #1
6. Quantity #2
7. Timeframe #1
8. Timeframe #2
... continue pattern to {max_questions} questions

⚠️ BALANCE: Make ~50% Boolean likely YES, ~50% likely NO (avoid all-positive bias)

QUESTION TYPES & EXAMPLES:

Boolean: "Will Bitcoin exceed $150K by Dec 31, 2025?" (specific threshold + future deadline)
MCQ: "Which company will IPO first: Stripe, SpaceX, Databricks, or Other?" (3-5 options + "Other")
Quantity: "Will ChatGPT reach 500M users by June 2025?" (numerical threshold)
Timeframe: "When will Apple announce iPhone 17: Q1, Q2, Q3, Q4 2025, or 2026+?" (date ranges)

QUALITY STANDARDS:
✓ Specific, measurable criteria  ✗ Vague ("Will crypto improve?")
✓ Clear resolution source         ✗ Subjective ("Will product succeed?")
✓ Natural deadlines (end of Q2)   ✗ Arbitrary dates (June 17 at 2pm)
✓ Verifiable outcomes              ✗ Unprovable claims

Use {tool_name} to save each question. Return brief summary when done.""",
        required_vars=["num_events", "events_text", "max_questions", "current_date", "max_resolution_date"],
        optional_vars={
            "domain_filter": "",
            "tool_name": "question_generator"
        }
    )
    
    def format_item(
        self,
        item: Event,
        idx: int,
        current_date: datetime,
        description_preview_length: int = 200,
        **context
    ) -> str:
        """Format a single event for the prompt.
        
        Args:
            item: Event to format
            idx: Index of the event (1-based)
            current_date: Current datetime for past event detection
            description_preview_length: Length of description preview (default: 200)
            **context: Additional context (not used)
            
        Returns:
            Formatted event summary
        """
        event_date = item.occurred_date or item.predicted_date
        
        # Determine if event is in the past (for ground truth)
        is_past_event = event_date and event_date < current_date if event_date else False
        status_note = " (PAST EVENT - questions should include ground_truth)" if is_past_event else ""
        
        # Truncate description
        description = self.truncate_text(
            item.description,
            max_length=description_preview_length,
            suffix="..."
        )
        
        # Extract metadata with safe defaults
        location = item.metadata.get('location', 'Unknown') if item.metadata else 'Unknown'
        confidence = item.metadata.get('confidence', 0.8) if item.metadata else 0.8
        
        return self.EVENT_TEMPLATE.format(
            idx=idx,
            event_id=item.id,
            status_note=status_note,
            title=item.title,
            description=description,
            event_date=event_date,
            domain=item.domain,
            location=location,
            confidence=confidence
        )
    
    def get_instruction(
        self,
        current_date: datetime,
        events: List[Event],
        max_questions: int,
        domains: Optional[List[str]] = None,
        description_preview_length: int = 200,
        tool_name: str = "question_generator",
        require_ground_truth: bool = True
    ) -> str:
        """Generate instruction for question generation.

        Args:
            current_date: Current datetime
            events: List of events to generate questions from
            max_questions: Maximum number of questions to generate
            domains: Optional list of domains to focus on
            description_preview_length: Length of description preview (default: 200)
            tool_name: Name of the tool to call (default: question_generator)
            require_ground_truth: If True, only generate questions about past events with known outcomes.
                                 If False, only generate questions about future predictions.

        Returns:
            Formatted instruction string
        """
        from datetime import timedelta

        date_str = self.format_datetime(current_date)

        # Calculate resolution date range based on mode
        if require_ground_truth:
            # Ground truth mode: Use past events only
            # Min: earliest event date (or 1 year ago)
            # Max: current_date (only events that already occurred)
            event_dates = []
            for event in events:
                event_date = event.occurred_date or event.predicted_date
                if event_date and event_date < current_date:
                    event_dates.append(event_date)

            if event_dates:
                min_resolution_date = min(event_dates)
            else:
                min_resolution_date = current_date - timedelta(days=365)

            max_resolution_date = current_date
        else:
            # Future prediction mode: Use future dates only
            # Min: current_date (tomorrow onwards)
            # Max: current_date + 1 year (reasonable forecasting horizon)
            min_resolution_date = current_date
            max_resolution_date = current_date + timedelta(days=365)

        min_res_str = self.format_datetime(min_resolution_date)
        max_res_str = self.format_datetime(max_resolution_date)

        # Format all events
        events_text = self.format_items(
            events,
            current_date=current_date,
            description_preview_length=description_preview_length
        )

        # Build domain filter
        domain_filter = ""
        if domains:
            domain_filter = f" Focus on domains: {self.format_list(domains)}."

        # Select appropriate template based on mode
        if require_ground_truth:
            template = self.GENERATION_TEMPLATE_GROUND_TRUTH
            instruction_body = template.format(
                num_events=len(events),
                events_text=events_text,
                max_questions=max_questions,
                current_date=date_str,
                min_resolution_date=min_res_str,
                domain_filter=domain_filter,
                tool_name=tool_name
            )
        else:
            template = self.GENERATION_TEMPLATE_FUTURE
            instruction_body = template.format(
                num_events=len(events),
                events_text=events_text,
                max_questions=max_questions,
                current_date=date_str,
                max_resolution_date=max_res_str,
                domain_filter=domain_filter,
                tool_name=tool_name
            )

        return f"Today's date is {date_str}.\n\n{instruction_body}"
