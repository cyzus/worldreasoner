"""Deterministic validation and atomic commit for staged construction graphs."""

from typing import Dict, List, Optional, Set
from uuid import uuid4

from src.config.pipeline import EvidenceSatisfactionConfig
from src.core.database import GenericDatabase
from src.domain.models import (
    AgentAlias,
    AliasEntityKind,
    ArtifactStatus,
    CausalHypothesis,
    CausalRelationType,
    Domain,
    Event,
    EventOutcomeImpact,
    EventStatus,
    EventType,
    ExplanationArtifact,
    GraphRevision,
    ImpactDirection,
    Question,
)
from src.services.pipeline_artifact_service import ArtifactValidationError
from src.services.question_monitor_service import QuestionMonitorService
from src.services.service_base import ServiceBase


class ConstructionGraphService(ServiceBase):
    """Keep agent graph proposals isolated until deterministic checks pass."""

    def __init__(
        self,
        db: GenericDatabase,
        requirements: Optional[EvidenceSatisfactionConfig] = None,
    ) -> None:
        super().__init__(db)
        self.requirements = requirements or EvidenceSatisfactionConfig()
        self.monitor = QuestionMonitorService(db, self.requirements)
        for model in (
            GraphRevision,
            AgentAlias,
            Question,
            Event,
            CausalHypothesis,
            EventOutcomeImpact,
        ):
            self.db.create_table(model)

    def validate(self, revision: GraphRevision) -> Dict[str, object]:
        """Return validation metadata or raise typed validation errors."""
        explanation = self.db.get(
            ExplanationArtifact, revision.explanation_artifact_id
        )
        errors: List[str] = []
        if explanation is None:
            errors.append("unknown_explanation")
            raise ArtifactValidationError(errors)
        if explanation.status != ArtifactStatus.VALIDATED:
            errors.append("explanation_not_validated")
        question = self.db.get(Question, revision.question_id)
        if question is None:
            errors.append("unknown_question")

        evidence_aliases = self._alias_map(
            revision.run_id,
            explanation.evidence_dossier_id,
            AliasEntityKind.ARTICLE,
        )
        outcome_aliases = self._alias_map(
            revision.run_id,
            revision.id,
            AliasEntityKind.OUTCOME,
        )
        node_map = {node.alias: node for node in revision.nodes}
        if len(node_map) != len(revision.nodes):
            errors.append("duplicate_node_alias")
        if not node_map:
            errors.append("empty_graph")

        for node in revision.nodes:
            if node.is_outcome:
                errors.append(f"agent_defined_outcome:{node.alias}")
            if node.occurred_date is None:
                errors.append(f"missing_event_date:{node.alias}")
            elif (
                question is not None
                and node.occurred_date.date() > question.resolution_date.date()
            ):
                errors.append(f"event_after_resolution:{node.alias}")
            if not node.evidence_aliases:
                errors.append(f"missing_node_evidence:{node.alias}")
            errors.extend(
                self._unknown_evidence(
                    node.evidence_aliases, evidence_aliases, node.alias
                )
            )
            if node.domain not in {item.value for item in Domain}:
                errors.append(f"invalid_node_domain:{node.alias}:{node.domain}")
            if node.event_type not in {item.value for item in EventType}:
                errors.append(
                    f"invalid_event_type:{node.alias}:{node.event_type}"
                )

        adjacency: Dict[str, Set[str]] = {alias: set() for alias in node_map}
        targets_outcome: Set[str] = set()
        for edge in revision.edges:
            if edge.source_alias not in node_map:
                errors.append(f"unknown_edge_source:{edge.source_alias}")
                continue
            if edge.target_alias in node_map:
                if edge.source_alias == edge.target_alias:
                    errors.append(f"self_loop:{edge.source_alias}")
                source_date = node_map[edge.source_alias].occurred_date
                target_date = node_map[edge.target_alias].occurred_date
                if (
                    source_date is not None
                    and target_date is not None
                    and source_date.date() > target_date.date()
                ):
                    errors.append(
                        "non_chronological_edge:"
                        f"{edge.source_alias}->{edge.target_alias}"
                    )
                adjacency[edge.source_alias].add(edge.target_alias)
            elif edge.target_alias in outcome_aliases:
                targets_outcome.add(edge.source_alias)
            else:
                errors.append(f"unknown_edge_target:{edge.target_alias}")
            errors.extend(
                self._unknown_evidence(
                    edge.evidence_aliases, evidence_aliases, "edge"
                )
            )
            if edge.relation not in {item.value for item in CausalRelationType}:
                errors.append(f"invalid_edge_relation:{edge.relation}")

        has_cycle = self._has_cycle(adjacency)
        if has_cycle:
            errors.append("cycle_detected")

        impact_pairs: Set[tuple[str, str]] = set()
        for impact in revision.outcome_impacts:
            if impact.event_alias not in node_map:
                errors.append(f"unknown_impact_event:{impact.event_alias}")
            if impact.outcome_alias not in outcome_aliases:
                errors.append(f"unknown_impact_outcome:{impact.outcome_alias}")
            impact_pairs.add((impact.event_alias, impact.outcome_alias))
            if (
                impact.event_alias in node_map
                and impact.outcome_alias in outcome_aliases
            ):
                targets_outcome.add(impact.event_alias)
            errors.extend(
                self._unknown_evidence(
                    impact.evidence_aliases, evidence_aliases, "impact"
                )
            )
            if impact.direction not in {item.value for item in ImpactDirection}:
                errors.append(f"invalid_impact_direction:{impact.direction}")
        for alias in node_map:
            if not any(event_alias == alias for event_alias, _ in impact_pairs):
                errors.append(f"missing_outcome_impact:{alias}")
        for alias in node_map:
            if not self._reaches_outcome(alias, adjacency, targets_outcome):
                errors.append(f"disconnected_from_outcome:{alias}")

        graph_depth = (
            0
            if has_cycle
            else self._max_depth_to_outcome(adjacency, targets_outcome)
        )
        total_event_count = len(node_map) + 1
        errors.extend(
            self.monitor.evaluate_graph_requirements(
                max_depth=graph_depth,
                event_count=total_event_count,
                hypothesis_count=len(revision.edges),
            )
        )

        if errors:
            revision.status = ArtifactStatus.REJECTED
            revision.validation_results = {"valid": False, "errors": errors}
            self.db.save(GraphRevision, revision)
            raise ArtifactValidationError(errors)
        results: Dict[str, object] = {
            "valid": True,
            "node_count": len(node_map),
            "edge_count": len(revision.edges),
            "impact_count": len(revision.outcome_impacts),
            "graph_depth": graph_depth,
            "total_event_count": total_event_count,
        }
        revision.status = ArtifactStatus.VALIDATED
        revision.validation_results = results
        self.db.save(GraphRevision, revision)
        return results

    def commit(self, revision_id: str) -> GraphRevision:
        """Atomically materialize one previously validated graph revision."""
        revision = self.db.get(GraphRevision, revision_id)
        if revision is None:
            raise ArtifactValidationError(["unknown_graph_revision"])
        if revision.status != ArtifactStatus.VALIDATED:
            raise ArtifactValidationError(["graph_revision_not_validated"])
        explanation = self.db.get(
            ExplanationArtifact, revision.explanation_artifact_id
        )
        question = self.db.get(Question, revision.question_id)
        if explanation is None or question is None:
            raise ArtifactValidationError(["missing_graph_parent"])
        article_aliases = self._alias_map(
            revision.run_id,
            explanation.evidence_dossier_id,
            AliasEntityKind.ARTICLE,
        )
        outcome_aliases = self._alias_map(
            revision.run_id,
            revision.id,
            AliasEntityKind.OUTCOME,
        )
        article_ids = self._quality_versions_to_articles(article_aliases)
        event_ids = {node.alias: str(uuid4()) for node in revision.nodes}

        events = [
            Event(
                id=event_ids[node.alias],
                title=node.title,
                description=node.description,
                event_type=EventType(node.event_type),
                domain=Domain(node.domain),
                occurred_date=node.occurred_date,
                status=EventStatus.OCCURRED,
                article_ids=[article_ids[alias] for alias in node.evidence_aliases],
                extracted_for_question_id=revision.question_id,
                metadata={"graph_revision_id": revision.id, "alias": node.alias},
            )
            for node in revision.nodes
        ]
        hypotheses = []
        for edge in revision.edges:
            target_id = (
                event_ids.get(edge.target_alias)
                or outcome_aliases[edge.target_alias]
            )
            hypotheses.append(
                CausalHypothesis(
                    id=str(uuid4()),
                    source_event_id=event_ids[edge.source_alias],
                    target_event_id=target_id,
                    relation_type=CausalRelationType(edge.relation),
                    strength=edge.strength,
                    confidence=edge.confidence,
                    reasoning=edge.reasoning,
                    evidence_article_ids=[
                        article_ids[alias] for alias in edge.evidence_aliases
                    ],
                    discovered_by_question_ids=[revision.question_id],
                    identified_by="construction_pipeline_v2",
                )
            )
        impacts = [
            EventOutcomeImpact(
                id=str(uuid4()),
                event_id=event_ids[impact.event_alias],
                outcome_event_id=outcome_aliases[impact.outcome_alias],
                question_id=revision.question_id,
                impact_direction=ImpactDirection(impact.direction),
                impact_magnitude=impact.magnitude,
                confidence=impact.confidence,
                reasoning=impact.reasoning,
                evidence_article_ids=[
                    article_ids[alias] for alias in impact.evidence_aliases
                ],
                discovered_by_question_ids=[revision.question_id],
                identified_by="construction_pipeline_v2",
            )
            for impact in revision.outcome_impacts
        ]
        with self.db.batch():
            for item in events:
                self.db.save(Event, item)
            for item in hypotheses:
                self.db.save(CausalHypothesis, item)
            for item in impacts:
                self.db.save(EventOutcomeImpact, item)
            question.related_event_ids = [item.id for item in events]
            question.graph_built = True
            question.graph_build_error = None
            self.db.save(Question, question)
            revision.status = ArtifactStatus.COMMITTED
            revision.validation_results["event_ids"] = event_ids
            self.db.save(GraphRevision, revision)
        return revision

    def _alias_map(
        self, run_id: str, scope_id: str, kind: AliasEntityKind
    ) -> Dict[str, str]:
        aliases = self.db.get_many(
            AgentAlias,
            filters={
                "run_id": run_id,
                "scope_id": scope_id,
                "entity_kind": kind.value,
            },
        )
        return {item.alias: item.target_id for item in aliases}

    def _quality_versions_to_articles(
        self, aliases: Dict[str, str]
    ) -> Dict[str, str]:
        from src.domain.models import ArticleQualityRecord

        result: Dict[str, str] = {}
        for alias, version_id in aliases.items():
            record = self.db.get(ArticleQualityRecord, version_id)
            if record is None:
                raise ArtifactValidationError([f"missing_article_version:{version_id}"])
            result[alias] = record.article_id
        return result

    @staticmethod
    def _unknown_evidence(
        aliases: List[str], approved: Dict[str, str], owner: str
    ) -> List[str]:
        return [
            f"unknown_evidence:{owner}:{alias}"
            for alias in aliases
            if alias not in approved
        ]

    @staticmethod
    def _has_cycle(adjacency: Dict[str, Set[str]]) -> bool:
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(child) for child in adjacency[node]):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in adjacency)

    @staticmethod
    def _reaches_outcome(
        start: str,
        adjacency: Dict[str, Set[str]],
        targets_outcome: Set[str],
    ) -> bool:
        pending = [start]
        visited: Set[str] = set()
        while pending:
            node = pending.pop()
            if node in targets_outcome:
                return True
            if node in visited:
                continue
            visited.add(node)
            pending.extend(adjacency[node])
        return False

    @staticmethod
    def _max_depth_to_outcome(
        adjacency: Dict[str, Set[str]], targets_outcome: Set[str]
    ) -> int:
        """Return the longest edge count from a proposal node to an outcome."""
        memo: Dict[str, int] = {}

        def depth(node: str) -> int:
            if node in memo:
                return memo[node]
            child_depths = [depth(child) for child in adjacency[node]]
            direct_depth = 1 if node in targets_outcome else 0
            memo[node] = max([direct_depth, *[1 + item for item in child_depths]])
            return memo[node]

        return max((depth(node) for node in adjacency), default=0)
