"""Tool to batch-create events and edges using structured JSON input."""

from typing import Optional

from smolagents import Tool

from src.tools.base.base import ToolResponseMixin
from src.tools.base.schema_helper import pydantic_to_output_schema
from src.tools.base.output_models import SubgraphOutput
from src.core.alias_registry import AliasRegistry


# Using local model to enforce structured input schema
# Note: we mirror the schema inside the tool so smolagents auto-generates the input dict
class ProposeSubgraphTool(Tool, ToolResponseMixin):
    """Tool to batch create events and edges for a causal graph."""

    name = "propose_subgraph"
    description = """Batch create events and edges in a single call to build the causal graph.
    
    This avoids having to call event_identifier and causal_reasoner dozens of times manually.
    Provide a JSON object with 'events' (list of event definitions) and 'edges' (list of causal links).
    """

    inputs = {
        "subgraph_json": {
            "type": "string",
            "description": "JSON object with 'events' and 'edges'. Events: {alias, title, description, domain, occurred_date, article_ids}. Edges: {source, target, relation, strength, confidence, reasoning}. 'source' and 'target' should match event aliases.",
        }
    }
    output_type = "object"
    output_schema = pydantic_to_output_schema(SubgraphOutput)

    @staticmethod
    def _clean_edge_error(reason: str) -> str:
        """Normalize internal tool errors into concise user-facing messages."""
        if not reason:
            return "Unknown validation error"

        cleaned = " ".join(str(reason).split())
        lowered = cleaned.lower()

        if lowered.startswith("chronology violation"):
            return cleaned.replace(
                "Chronology violation:",
                "Invalid chronology:",
                1,
            )
        return cleaned

    def __init__(
        self,
        event_identifier_tool,
        causal_reasoner_tool,
        alias_registry: AliasRegistry,
        db_path: str = None,
        question_id: Optional[str] = None,
    ):
        """Initialize the tool.

        Args:
            event_identifier_tool: Instance of EventIdentifierTool
            causal_reasoner_tool: Instance of CausalReasonerTool
            alias_registry: Registry to map semantic names to event UUIDs
        """
        super().__init__()
        self.question_id = question_id
        self.event_tool = event_identifier_tool
        self.reasoner_tool = causal_reasoner_tool
        self.alias_registry = alias_registry

        from src.core.database import GenericDatabase

        self.db = GenericDatabase(db_path) if db_path else None

    def forward(self, subgraph_json: str) -> str:
        """Batch create events and edges."""
        import json

        try:
            subgraph = json.loads(subgraph_json)
        except json.JSONDecodeError as e:
            return SubgraphOutput(
                status="error",
                events_created=0,
                edges_created=0,
                failed_items=[
                    {"type": "parse_error", "reason": f"Invalid JSON: {str(e)}"}
                ],
            )

        events = subgraph.get("events", [])
        edges = subgraph.get("edges", [])

        events_created = 0
        edges_created = 0
        failed_items = []

        # 1. Process Events
        for ev in events:
            alias = ev.get("alias")
            if not alias:
                failed_items.append(
                    {"type": "event", "item": ev, "reason": "Missing 'alias' field"}
                )
                continue

            try:
                # Call EventIdentifierTool
                # Map structured input back to tool arguments
                title = ev.get("title", "Unknown Event")
                desc = ev.get("description", "")
                domain = ev.get("domain", "politics")

                art_ids = ev.get("article_ids", [])
                if isinstance(art_ids, list):
                    raw_ids = art_ids
                else:
                    raw_ids = [a.strip() for a in str(art_ids).split(",") if a.strip()]

                # Resolve article aliases (e.g. A1:BBCSanctions -> real ID)
                if self.alias_registry and raw_ids:
                    raw_ids = [
                        self.alias_registry.resolve(aid) or aid for aid in raw_ids
                    ]

                # Filter to IDs that actually exist in DB to avoid hard validation failures
                if self.db and raw_ids:
                    from src.domain.models import Article
                    valid_ids = [aid for aid in raw_ids if self.db.get(Article, aid) is not None]
                else:
                    valid_ids = raw_ids
                art_ids_str = ",".join(valid_ids)

                occurred_date = ev.get("occurred_date", "")

                # We do NOT pass alias to event_identifier inputs directly,
                # but we will register the resulting ID in our alias registry!

                resp = self.event_tool.forward(
                    title=title,
                    description=desc,
                    domain=domain,
                    source_article_ids=art_ids_str,
                    occurred_date=occurred_date,
                )

                # EventIdentifier returns EventOutput on success or a JSON error string on failure
                if isinstance(resp, str):
                    import json as _json
                    try:
                        err = _json.loads(resp)
                        reason = err.get("message") or err.get("error") or resp
                    except Exception:
                        reason = resp
                    failed_items.append({"type": "event", "alias": alias, "reason": reason})
                    continue

                event_id = getattr(resp, "id", None)
                event_status = str(getattr(resp, "status", "")).strip()

                # EventIdentifierTool may return EventOutput(id="error", status="error: ...")
                # for validation failures. Treat these as failures and do not register aliases.
                if event_id == "error" or event_status.lower().startswith("error"):
                    reason = event_status or "Event validation failed"
                    failed_items.append(
                        {
                            "type": "event",
                            "alias": alias,
                            "reason": reason,
                        }
                    )
                    continue

                if not event_id:
                    failed_items.append(
                        {
                            "type": "event",
                            "alias": alias,
                            "reason": "Tool failed to return an ID",
                        }
                    )
                else:
                    self.alias_registry.register(alias, event_id)
                    events_created += 1

            except Exception as e:
                failed_items.append({"type": "event", "alias": alias, "reason": str(e)})

        # 2. Process Edges
        for ed in edges:
            source_alias = ed.get("source")
            target_alias = ed.get("target")

            if not source_alias or not target_alias:
                failed_items.append(
                    {
                        "type": "edge",
                        "item": ed,
                        "reason": "Missing source or target alias",
                    }
                )
                continue

            # Resolve aliases to UUIDs
            source_id = self.alias_registry.resolve(source_alias) or source_alias
            target_id = self.alias_registry.resolve(target_alias) or target_alias

            # Alias resolver can carry unresolved values as "error".
            if source_id == "error" or target_id == "error":
                unresolved = source_alias if source_id == "error" else target_alias
                failed_items.append(
                    {
                        "type": "edge",
                        "source": source_alias,
                        "target": target_alias,
                        "reason": (
                            f"Unresolved event alias '{unresolved}'. "
                            "Create that event first, then retry this edge."
                        ),
                    }
                )
                continue

            try:
                # Call CausalReasonerTool
                resp = self.reasoner_tool.forward(
                    source_event_id=source_id,
                    target_event_id=target_id,
                    relation_type=ed.get("relation", "causes"),
                    strength=float(ed.get("strength", 0.5)),
                    confidence=float(ed.get("confidence", 0.5)),
                    reasoning=ed.get("reasoning", ""),
                )

                # CausalReasonerTool returns HypothesisOutput on success or a JSON error string
                if isinstance(resp, str):
                    import json as _json
                    try:
                        err = _json.loads(resp)
                        reason = err.get("message") or err.get("error") or resp
                    except Exception:
                        reason = resp
                    failed_items.append(
                        {
                            "type": "edge",
                            "source": source_alias,
                            "target": target_alias,
                            "reason": self._clean_edge_error(reason),
                        }
                    )
                elif getattr(resp, "status", "error") == "error":
                    error_msg = getattr(resp, "error", "Unknown validation error")
                    failed_items.append(
                        {
                            "type": "edge",
                            "source": source_alias,
                            "target": target_alias,
                            "reason": self._clean_edge_error(error_msg),
                        }
                    )
                else:
                    edges_created += 1

            except Exception as e:
                failed_items.append(
                    {
                        "type": "edge",
                        "source": source_alias,
                        "target": target_alias,
                        "reason": str(e),
                    }
                )

        status = (
            "success"
            if not failed_items
            else "partial_success"
            if (events_created > 0 or edges_created > 0)
            else "error"
        )

        return SubgraphOutput(
            status=status,
            events_created=events_created,
            edges_created=edges_created,
            failed_items=failed_items,
            alias_map=self.alias_registry.list_aliases(),
        )
