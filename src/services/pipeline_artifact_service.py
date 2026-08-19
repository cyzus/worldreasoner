"""Runtime-neutral persistence for construction runs and agent aliases."""

from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.core.database import GenericDatabase
from src.domain.models import (
    AgentAlias,
    AliasEntityKind,
    AliasScopeType,
    ApprovedEvidenceDossier,
    ArtifactStatus,
    ExplanationArtifact,
    GraphRevision,
    PipelineRun,
    PipelineRunStatus,
    SearchDossier,
    StageAttempt,
    StageAttemptStatus,
)
from src.services.service_base import ServiceBase


class AliasResolutionError(ValueError):
    """Raised when an agent reference cannot be resolved unambiguously."""


class PipelineStateError(ValueError):
    """Raised when a requested run or stage transition is invalid."""


class ArtifactValidationError(ValueError):
    """Raised when a versioned artifact violates deterministic contracts."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class PipelineArtifactService(ServiceBase):
    """Persist pipeline lifecycle state independently of an agent runtime."""

    _MODELS = (
        PipelineRun,
        StageAttempt,
        SearchDossier,
        ApprovedEvidenceDossier,
        ExplanationArtifact,
        GraphRevision,
        AgentAlias,
    )

    def __init__(self, db: GenericDatabase):
        super().__init__(db)
        for model in self._MODELS:
            self.db.create_table(model)

    def start_run(
        self,
        question_id: str,
        dataset_version: str,
        workflow_version: str,
        model_configuration: Optional[Dict[str, object]] = None,
        prompt_bundle_version: Optional[str] = None,
        parent_run_id: Optional[str] = None,
    ) -> PipelineRun:
        """Create a running construction workflow."""
        run = PipelineRun(
            question_id=question_id,
            dataset_version=dataset_version,
            workflow_version=workflow_version,
            status=PipelineRunStatus.RUNNING,
            model_configuration=model_configuration or {},
            prompt_bundle_version=prompt_bundle_version,
            parent_run_id=parent_run_id,
        )
        self.db.save(PipelineRun, run)
        return run

    def start_stage_attempt(
        self,
        run_id: str,
        stage_name: str,
        idempotency_key: str,
        input_artifact_ids: Optional[List[str]] = None,
    ) -> StageAttempt:
        """Start a stage once, returning an existing attempt for the same key."""
        run = self._require_running_run(run_id)
        existing = self.db.get_many(
            StageAttempt,
            filters={"run_id": run_id, "idempotency_key": idempotency_key},
        )
        if existing:
            attempt = existing[0]
            if attempt.stage_name != stage_name:
                raise PipelineStateError(
                    "An idempotency key cannot be reused for another stage"
                )
            return attempt

        previous = self.db.get_many(
            StageAttempt,
            filters={"run_id": run_id, "stage_name": stage_name},
        )
        attempt = StageAttempt(
            run_id=run_id,
            stage_name=stage_name,
            attempt_number=len(previous) + 1,
            idempotency_key=idempotency_key,
            input_artifact_ids=input_artifact_ids or [],
        )
        with self.db.batch():
            self.db.save(StageAttempt, attempt)
            run.current_stage = stage_name
            self.db.save(PipelineRun, run)
        return attempt

    def finish_stage_attempt(
        self,
        attempt_id: str,
        status: StageAttemptStatus,
        output_artifact_ids: Optional[List[str]] = None,
        failure_code: Optional[str] = None,
        retryable: bool = False,
        diagnostic: Optional[str] = None,
        token_usage: int = 0,
        cost_usd: float = 0.0,
    ) -> StageAttempt:
        """Record the terminal result and aggregate usage onto the run."""
        if status == StageAttemptStatus.RUNNING:
            raise PipelineStateError("A finished stage cannot remain running")
        attempt = self.db.get(StageAttempt, attempt_id)
        if attempt is None:
            raise PipelineStateError(f"Unknown stage attempt: {attempt_id}")
        if attempt.status != StageAttemptStatus.RUNNING:
            return attempt

        run = self.db.get(PipelineRun, attempt.run_id)
        if run is None:
            raise PipelineStateError(f"Unknown pipeline run: {attempt.run_id}")

        attempt.status = status
        attempt.output_artifact_ids = output_artifact_ids or []
        attempt.failure_code = failure_code
        attempt.retryable = retryable
        attempt.diagnostic = diagnostic
        attempt.token_usage = token_usage
        attempt.cost_usd = cost_usd
        attempt.completed_at = datetime.now(timezone.utc)
        run.token_usage += token_usage
        run.cost_usd += cost_usd

        if status == StageAttemptStatus.NEEDS_REVIEW:
            run.status = PipelineRunStatus.NEEDS_REVIEW
        elif status == StageAttemptStatus.TERMINAL_FAILURE:
            run.status = PipelineRunStatus.FAILED
            run.error_summary = diagnostic or failure_code

        with self.db.batch():
            self.db.save(StageAttempt, attempt)
            self.db.save(PipelineRun, run)
        return attempt

    def register_aliases(
        self,
        run_id: str,
        scope_id: str,
        scope_type: AliasScopeType,
        entity_kind: AliasEntityKind,
        target_ids: List[str],
        is_canonical: bool = True,
    ) -> Dict[str, str]:
        """Assign stable aliases, preserving mappings already stored in a scope."""
        self._require_run(run_id)
        prefix = {
            AliasEntityKind.ARTICLE: "A",
            AliasEntityKind.EVENT: "E",
            AliasEntityKind.OUTCOME: "O",
        }[entity_kind]
        existing = self.db.get_many(
            AgentAlias, filters={"run_id": run_id, "scope_id": scope_id}
        )
        mapping = {
            item.alias: item.target_id
            for item in existing
            if item.entity_kind == entity_kind
        }
        target_to_alias = {target: alias for alias, target in mapping.items()}
        used_numbers = [
            int(alias[1:])
            for alias in mapping
            if alias.startswith(prefix) and alias[1:].isdigit()
        ]
        next_number = max(used_numbers, default=0) + 1
        additions: List[AgentAlias] = []

        for target_id in target_ids:
            if target_id in target_to_alias:
                continue
            alias = f"{prefix}{next_number:02d}"
            next_number += 1
            additions.append(
                AgentAlias(
                    run_id=run_id,
                    scope_id=scope_id,
                    scope_type=scope_type,
                    alias=alias,
                    entity_kind=entity_kind,
                    target_id=target_id,
                    is_canonical=is_canonical,
                )
            )
            mapping[alias] = target_id
            target_to_alias[target_id] = alias

        if additions:
            with self.db.batch():
                for item in additions:
                    self.db.save(AgentAlias, item)
        return mapping

    def save_validated_explanation(
        self, explanation: ExplanationArtifact
    ) -> ExplanationArtifact:
        """Validate and persist one immutable explanation artifact."""
        if self.db.get(ExplanationArtifact, explanation.id) is not None:
            raise PipelineStateError(
                f"Explanation artifact already exists: {explanation.id}"
            )
        self.validate_explanation_citations(explanation)
        explanation.status = ArtifactStatus.VALIDATED
        self.db.save(ExplanationArtifact, explanation)
        return explanation

    def validate_explanation_citations(self, explanation: ExplanationArtifact) -> None:
        """Require every citation to resolve inside the approved dossier."""
        dossier = self.db.get(ApprovedEvidenceDossier, explanation.evidence_dossier_id)
        if dossier is None:
            raise ArtifactValidationError(
                [
                    f"Unknown approved evidence dossier: {explanation.evidence_dossier_id}"
                ]
            )
        errors: List[str] = []
        if dossier.run_id != explanation.run_id:
            errors.append("Explanation and evidence dossier belong to different runs")
        if dossier.question_id != explanation.question_id:
            errors.append(
                "Explanation and evidence dossier belong to different questions"
            )
        if dossier.status != ArtifactStatus.VALIDATED:
            errors.append("Evidence dossier is not validated")

        aliases = self.db.get_many(
            AgentAlias,
            filters={
                "run_id": explanation.run_id,
                "scope_id": dossier.id,
                "entity_kind": AliasEntityKind.ARTICLE.value,
            },
        )
        alias_map = {item.alias: item.target_id for item in aliases}
        approved_versions = set(dossier.article_version_ids)

        for section in explanation.sections:
            for alias in section.citation_aliases:
                if alias not in alias_map:
                    errors.append(
                        f"Section {section.id} cites unknown article alias {alias}"
                    )

        for event in explanation.event_candidates:
            if not event.evidence_refs:
                errors.append(f"Event {event.alias} has no evidence references")
            for reference in event.evidence_refs:
                resolved_id = alias_map.get(reference.article_alias)
                if resolved_id is None:
                    errors.append(
                        f"Event {event.alias} cites unknown article alias "
                        f"{reference.article_alias}"
                    )
                    continue
                if resolved_id != reference.article_version_id:
                    errors.append(
                        f"Event {event.alias} citation {reference.article_alias} "
                        "does not match its approved article version"
                    )
                if reference.article_version_id not in approved_versions:
                    errors.append(
                        f"Event {event.alias} cites an article version outside the dossier"
                    )

        if errors:
            raise ArtifactValidationError(errors)

    def resolve_alias(
        self,
        run_id: str,
        scope_id: str,
        alias: str,
        expected_kind: AliasEntityKind,
    ) -> str:
        """Resolve an alias strictly; raw IDs and cross-scope aliases are rejected."""
        matches = self.db.get_many(
            AgentAlias,
            filters={"run_id": run_id, "scope_id": scope_id, "alias": alias},
        )
        if not matches:
            raise AliasResolutionError(f"Unknown alias '{alias}' in scope '{scope_id}'")
        if len(matches) > 1:
            raise AliasResolutionError(
                f"Ambiguous alias '{alias}' in scope '{scope_id}'"
            )
        match = matches[0]
        if match.entity_kind != expected_kind:
            raise AliasResolutionError(
                f"Alias '{alias}' refers to {match.entity_kind.value}, "
                f"not {expected_kind.value}"
            )
        return match.target_id

    def _require_run(self, run_id: str) -> PipelineRun:
        run = self.db.get(PipelineRun, run_id)
        if run is None:
            raise PipelineStateError(f"Unknown pipeline run: {run_id}")
        return run

    def _require_running_run(self, run_id: str) -> PipelineRun:
        run = self._require_run(run_id)
        if run.status != PipelineRunStatus.RUNNING:
            raise PipelineStateError(
                f"Pipeline run '{run_id}' is not running: {run.status.value}"
            )
        return run
