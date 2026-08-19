"""Tests for resumable pipeline state and strict agent aliases."""

import pytest

from src.core.database import GenericDatabase
from src.domain.models import (
    AgentAlias,
    AliasEntityKind,
    AliasScopeType,
    ApprovedEvidenceDossier,
    ArtifactStatus,
    EventCandidate,
    EvidenceReference,
    EvidenceSupportType,
    ExplanationArtifact,
    ExplanationSection,
    PipelineRun,
    PipelineRunStatus,
    StageAttempt,
    StageAttemptStatus,
)
from src.services.pipeline_artifact_service import (
    AliasResolutionError,
    ArtifactValidationError,
    PipelineArtifactService,
    PipelineStateError,
)


@pytest.fixture
def service(test_db_path: str) -> PipelineArtifactService:
    return PipelineArtifactService(GenericDatabase(test_db_path))


def test_start_run_persists_runtime_neutral_provenance(
    service: PipelineArtifactService,
) -> None:
    run = service.start_run(
        question_id="q1",
        dataset_version="v2.0",
        workflow_version="pipeline-v1",
        model_configuration={"explanation": "test-model"},
        prompt_bundle_version="prompts-v1",
    )

    stored = service.db.get(PipelineRun, run.id)

    assert stored is not None
    assert stored.status == PipelineRunStatus.RUNNING
    assert stored.model_configuration == {"explanation": "test-model"}


def test_stage_start_is_idempotent_and_updates_current_stage(
    service: PipelineArtifactService,
) -> None:
    run = service.start_run("q1", "v2.0", "pipeline-v1")

    first = service.start_stage_attempt(run.id, "cleaning", "q1:cleaning:v1")
    repeated = service.start_stage_attempt(run.id, "cleaning", "q1:cleaning:v1")

    assert repeated.id == first.id
    assert service.db.get(PipelineRun, run.id).current_stage == "cleaning"
    assert len(service.db.get_many(StageAttempt, filters={"run_id": run.id})) == 1


def test_idempotency_key_cannot_cross_stage_boundaries(
    service: PipelineArtifactService,
) -> None:
    run = service.start_run("q1", "v2.0", "pipeline-v1")
    service.start_stage_attempt(run.id, "cleaning", "shared-key")

    with pytest.raises(PipelineStateError, match="another stage"):
        service.start_stage_attempt(run.id, "explaining", "shared-key")


def test_finishing_stage_aggregates_usage_once(
    service: PipelineArtifactService,
) -> None:
    run = service.start_run("q1", "v2.0", "pipeline-v1")
    attempt = service.start_stage_attempt(run.id, "cleaning", "cleaning-1")

    service.finish_stage_attempt(
        attempt.id,
        StageAttemptStatus.SUCCEEDED,
        output_artifact_ids=["cleaned-1"],
        token_usage=125,
        cost_usd=0.25,
    )
    service.finish_stage_attempt(
        attempt.id,
        StageAttemptStatus.SUCCEEDED,
        token_usage=125,
        cost_usd=0.25,
    )

    stored_run = service.db.get(PipelineRun, run.id)
    stored_attempt = service.db.get(StageAttempt, attempt.id)
    assert stored_run.token_usage == 125
    assert stored_run.cost_usd == pytest.approx(0.25)
    assert stored_attempt.output_artifact_ids == ["cleaned-1"]


def test_terminal_failure_updates_run_state(service: PipelineArtifactService) -> None:
    run = service.start_run("q1", "v2.0", "pipeline-v1")
    attempt = service.start_stage_attempt(run.id, "graph_validation", "validate-1")

    service.finish_stage_attempt(
        attempt.id,
        StageAttemptStatus.TERMINAL_FAILURE,
        failure_code="unsupported_event",
        diagnostic="E03 has no approved evidence",
    )

    stored = service.db.get(PipelineRun, run.id)
    assert stored.status == PipelineRunStatus.FAILED
    assert stored.error_summary == "E03 has no approved evidence"


def test_aliases_are_stable_when_scope_is_extended(
    service: PipelineArtifactService,
) -> None:
    run = service.start_run("q1", "v2.0", "pipeline-v1")

    initial = service.register_aliases(
        run.id,
        "dossier-1",
        AliasScopeType.EVIDENCE_DOSSIER,
        AliasEntityKind.ARTICLE,
        ["article-long-id-1", "article-long-id-2"],
    )
    extended = service.register_aliases(
        run.id,
        "dossier-1",
        AliasScopeType.EVIDENCE_DOSSIER,
        AliasEntityKind.ARTICLE,
        ["article-long-id-2", "article-long-id-3"],
    )

    assert initial == {"A01": "article-long-id-1", "A02": "article-long-id-2"}
    assert extended == {
        "A01": "article-long-id-1",
        "A02": "article-long-id-2",
        "A03": "article-long-id-3",
    }
    assert len(service.db.get_many(AgentAlias, filters={"scope_id": "dossier-1"})) == 3


def test_alias_resolution_is_strict_and_kind_checked(
    service: PipelineArtifactService,
) -> None:
    run = service.start_run("q1", "v2.0", "pipeline-v1")
    service.register_aliases(
        run.id,
        "dossier-1",
        AliasScopeType.EVIDENCE_DOSSIER,
        AliasEntityKind.ARTICLE,
        ["article-long-id-1"],
    )

    assert (
        service.resolve_alias(run.id, "dossier-1", "A01", AliasEntityKind.ARTICLE)
        == "article-long-id-1"
    )
    with pytest.raises(AliasResolutionError, match="Unknown alias"):
        service.resolve_alias(
            run.id, "dossier-1", "article-long-id-1", AliasEntityKind.ARTICLE
        )
    with pytest.raises(AliasResolutionError, match="not event"):
        service.resolve_alias(run.id, "dossier-1", "A01", AliasEntityKind.EVENT)


def test_validated_explanation_round_trips_structured_citations(
    service: PipelineArtifactService,
) -> None:
    run = service.start_run("q1", "v2.0", "pipeline-v1")
    dossier = ApprovedEvidenceDossier(
        run_id=run.id,
        question_id="q1",
        dataset_version="v2.0",
        search_dossier_id="search-1",
        article_version_ids=["article-version-1"],
        readiness_decision="ready",
        status=ArtifactStatus.VALIDATED,
    )
    service.db.save(ApprovedEvidenceDossier, dossier)
    service.register_aliases(
        run.id,
        dossier.id,
        AliasScopeType.EVIDENCE_DOSSIER,
        AliasEntityKind.ARTICLE,
        ["article-version-1"],
    )
    explanation = ExplanationArtifact(
        run_id=run.id,
        question_id="q1",
        dataset_version="v2.0",
        evidence_dossier_id=dossier.id,
        sections=[
            ExplanationSection(
                id="S01", text="A documented event occurred.", citation_aliases=["A01"]
            )
        ],
        event_candidates=[
            EventCandidate(
                alias="E01",
                title="Documented event",
                description="A concrete event supported by the approved source.",
                evidence_refs=[
                    EvidenceReference(
                        article_alias="A01",
                        article_version_id="article-version-1",
                        support_type=EvidenceSupportType.DIRECT,
                    )
                ],
            )
        ],
        model="test-model",
        prompt_version="explanation-v1",
    )

    service.save_validated_explanation(explanation)
    stored = service.db.get(ExplanationArtifact, explanation.id)

    assert stored is not None
    assert stored.status == ArtifactStatus.VALIDATED
    assert stored.sections[0].citation_aliases == ["A01"]
    assert stored.event_candidates[0].evidence_refs[0].article_version_id == (
        "article-version-1"
    )


def test_explanation_rejects_unresolved_or_mismatched_citations(
    service: PipelineArtifactService,
) -> None:
    run = service.start_run("q1", "v2.0", "pipeline-v1")
    dossier = ApprovedEvidenceDossier(
        run_id=run.id,
        question_id="q1",
        dataset_version="v2.0",
        search_dossier_id="search-1",
        article_version_ids=["article-version-1"],
        readiness_decision="ready",
        status=ArtifactStatus.VALIDATED,
    )
    service.db.save(ApprovedEvidenceDossier, dossier)
    service.register_aliases(
        run.id,
        dossier.id,
        AliasScopeType.EVIDENCE_DOSSIER,
        AliasEntityKind.ARTICLE,
        ["article-version-1"],
    )
    explanation = ExplanationArtifact(
        run_id=run.id,
        question_id="q1",
        dataset_version="v2.0",
        evidence_dossier_id=dossier.id,
        sections=[ExplanationSection(id="S01", text="Claim", citation_aliases=["A99"])],
        event_candidates=[
            EventCandidate(
                alias="E01",
                title="Claim",
                description="Claim with a mismatched version.",
                evidence_refs=[
                    EvidenceReference(
                        article_alias="A01",
                        article_version_id="article-version-2",
                        support_type=EvidenceSupportType.DIRECT,
                    )
                ],
            )
        ],
        model="test-model",
        prompt_version="explanation-v1",
    )

    with pytest.raises(ArtifactValidationError) as error:
        service.save_validated_explanation(explanation)

    assert "unknown article alias A99" in str(error.value)
    assert "does not match its approved article version" in str(error.value)
    assert service.db.get(ExplanationArtifact, explanation.id) is None
