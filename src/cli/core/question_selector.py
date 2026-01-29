"""Interactive question selection with filtering and rich display.

Provides a reusable component for selecting questions with rich filtering,
display, and both single and multi-select modes.
"""

from typing import Optional, List, Set

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from src.core.database import GenericDatabase
from src.cli.core.question_manager import QuestionManager, QuestionFilter
from src.cli.ui.tables import display_question_table
from src.domain.models import Question


class QuestionSelector:
    """Interactive question selection with filtering and rich display.

    Provides a user-friendly way to select questions from the database
    with support for filtering, sorting, and both single and multi-select modes.
    """

    def __init__(self, db_path: str = "worldreasoner.db"):
        self.db = GenericDatabase(db_path)
        self.manager = QuestionManager(self.db)
        self.console = Console()

    def select_questions(
        self,
        source: Optional[str] = None,
        domain: Optional[str] = None,
        resolved_only: bool = False,
        has_evidence: Optional[bool] = None,
        min_quality_score: Optional[float] = None,
        limit: int = 50,
        multi_select: bool = True,
    ) -> List[Question]:
        """Display filtered questions and allow interactive selection.

        Args:
            source: Filter by question source (e.g., 'polymarket')
            domain: Filter by domain (e.g., 'politics', 'technology')
            resolved_only: Only show resolved questions
            has_evidence: Filter by whether question has evidence/hypotheses
            min_quality_score: Minimum quality score (0-1)
            limit: Maximum number of questions to display
            multi_select: Allow selecting multiple questions

        Returns:
            List of selected Question objects
        """
        # Build filter
        filter_obj = QuestionFilter(
            source=source,
            domain=domain,
            resolved_only=resolved_only,
            has_evidence=has_evidence,
            min_quality_score=min_quality_score,
        )

        # Load questions
        questions = self._load_questions(filter_obj, limit)

        if not questions:
            self.console.print(
                "[yellow]No questions match the selected filters[/yellow]"
            )
            return []

        # Display questions
        evidence_map = self.manager.get_evidence_status(questions)
        display_question_table(questions, evidence_map, self.console)

        # Get selection
        if multi_select:
            return self._multi_select(questions)
        else:
            return self._single_select(questions)

    def _load_questions(self, filter_obj: QuestionFilter, limit: int) -> List[Question]:
        """Load questions with filters applied."""
        return self.manager.query_questions(filter_obj, limit)

    def _multi_select(self, questions: List[Question]) -> List[Question]:
        """Allow selecting multiple questions."""
        self.console.print("\n[bold]Selection options:[/bold]")
        self.console.print("  - Enter numbers: [cyan]1,3,5-10[/cyan]")
        self.console.print("  - Select all: [cyan]all[/cyan]")
        self.console.print("  - Cancel: [cyan]q[/cyan] or empty")

        selection = Prompt.ask("\nSelect questions")

        if not selection or selection.lower() == "q":
            return []

        if selection.lower() == "all":
            return questions

        return self._parse_selection(selection, questions)

    def _single_select(self, questions: List[Question]) -> List[Question]:
        """Allow selecting a single question."""
        selection = Prompt.ask("\nSelect question number (or 'q' to cancel)")

        if not selection or selection.lower() == "q":
            return []

        try:
            idx = int(selection) - 1
            if 0 <= idx < len(questions):
                return [questions[idx]]
        except ValueError:
            pass

        self.console.print("[red]Invalid selection[/red]")
        return []

    def _parse_selection(
        self, selection: str, questions: List[Question]
    ) -> List[Question]:
        """Parse selection string like '1,3,5-10' into questions.

        Examples:
            '1,3,5' -> questions 1, 3, 5
            '1-5' -> questions 1-5 inclusive
            '1,3,5-8,10' -> mixed selection
        """
        indices: Set[int] = set()

        for part in selection.split(","):
            part = part.strip()
            if "-" in part:
                # Handle range like '5-10'
                try:
                    start, end = part.split("-")
                    start = int(start.strip())
                    end = int(end.strip())
                    indices.update(range(start, end + 1))
                except (ValueError, AttributeError):
                    self.console.print(f"[yellow]Invalid range: {part}[/yellow]")
            else:
                # Handle single number
                try:
                    indices.add(int(part))
                except ValueError:
                    self.console.print(f"[yellow]Invalid number: {part}[/yellow]")

        # Convert to 0-indexed and filter valid
        return [questions[i - 1] for i in sorted(indices) if 1 <= i <= len(questions)]

    def show_question_details(self, question_id: str) -> Optional[Question]:
        """Show detailed information about a single question."""
        question = self.db.get(Question, question_id)
        if not question:
            self.console.print(f"[red]Question not found: {question_id}[/red]")
            return None

        # Get related entity info from QuestionManager
        details = self.manager.show_question(question_id)

        info_lines = [
            f"[bold]ID:[/bold] {question.id}",
            f"[bold]Question:[/bold] {question.question_text}",
            f"[bold]Type:[/bold] {question.question_type.value if hasattr(question.question_type, 'value') else question.question_type}",
            f"[bold]Domain:[/bold] {question.domain.value if hasattr(question.domain, 'value') else question.domain}",
            f"[bold]Source:[/bold] {question.source}",
            f"[bold]Difficulty:[/bold] {question.difficulty}/5",
            f"[bold]Quality Score:[/bold] {question.quality_score or 'N/A'}",
            f"[bold]Resolution Date:[/bold] {question.resolution_date.isoformat() if question.resolution_date else 'N/A'}",
        ]

        if question.ground_truth is not None:
            info_lines.append(
                f"[bold]Ground Truth:[/bold] [green]{question.ground_truth}[/green]"
            )
        if question.context:
            info_lines.append(f"[bold]Context:[/bold] {question.context}")
        if question.resolution_criteria:
            info_lines.append(
                f"[bold]Resolution Criteria:[/bold] {question.resolution_criteria}"
            )

        if details:
            info_lines.append(f"[bold]Related Events:[/bold] {len(details['events'])}")
            info_lines.append(
                f"[bold]Related Articles:[/bold] {details['article_count']}"
            )
            info_lines.append(
                f"[bold]Causal Hypotheses:[/bold] {len(details['causal_hypotheses'])}"
            )

        content = "\n".join(info_lines)
        panel = Panel(content, title="Question Details", border_style="blue")
        self.console.print(panel)

        return question
