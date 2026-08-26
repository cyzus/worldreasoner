"""Two independent LLM passes for event-to-source grounding."""

import json
from typing import Any, Dict, List, Optional

from src.domain.models import (
    Article,
    DateLabel,
    EntityLabel,
    Event,
    EventEvidenceExtraction,
    EventEvidenceVerification,
    QualityStatus,
    RepairAction,
    SupportLabel,
)
from src.services.evidence_quality.article_normalizer import passage_is_traceable
from src.services.evidence_quality.llm_client import StructuredLLM


EXTRACTOR_PROMPT_VERSION = "event-evidence-extractor-v1"
VERIFIER_PROMPT_VERSION = "event-evidence-verifier-v2"
TRACEABILITY_VERSION = "markdown-visible-v2"
TRACEABILITY_GATE_MODEL = "deterministic/traceability-gate"


class EventEvidenceExtractor:
    """Extract exact passages without making the final validity decision."""

    def __init__(self, llm: StructuredLLM) -> None:
        self.llm = llm

    async def extract(
        self,
        event: Event,
        article: Article,
        input_content: str,
        traceability_snapshot: str,
        dataset_version: str,
    ) -> EventEvidenceExtraction:
        payload = await self.llm.complete_json(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(event, article, input_content),
        )
        supporting = self._string_list(payload.get("supporting_passages"))
        contradicting = self._string_list(payload.get("contradicting_passages"))
        date_passages = self._string_list(payload.get("date_passages"))
        all_passages = supporting + contradicting + date_passages
        failures = [
            passage
            for passage in all_passages
            if not passage_is_traceable(passage, traceability_snapshot)
        ]
        status = QualityStatus.COMPLETE if not failures else QualityStatus.NEEDS_REPAIR

        return EventEvidenceExtraction(
            event_id=event.id,
            article_id=article.id,
            dataset_version=dataset_version,
            supporting_passages=supporting,
            contradicting_passages=contradicting,
            date_passages=date_passages,
            proposed_claim=self._optional_string(payload.get("proposed_claim")),
            proposed_date=self._optional_string(payload.get("proposed_date")),
            all_passages_traceable=bool(all_passages) and not failures,
            traceability_failures=failures,
            traceability_version=TRACEABILITY_VERSION,
            status=status,
            model=self.llm.model_name,
            prompt_version=EXTRACTOR_PROMPT_VERSION,
        )

    @staticmethod
    def _system_prompt() -> str:
        return """You extract evidence for dataset validation. Copy only exact,
verbatim passages from the supplied article. Find passages that support or
contradict the event, and passages establishing its date. Do not decide whether
the event should be accepted. If the claim is broader than the evidence, propose
the smallest supported claim. Do not use outside knowledge. Return JSON only."""

    @staticmethod
    def _user_prompt(event: Event, article: Article, input_content: str) -> str:
        data = {
            "event": {
                "title": event.title,
                "description": event.description,
                "occurred_date": event.occurred_date.isoformat()
                if event.occurred_date
                else None,
            },
            "article": {
                "title": article.title,
                "url": article.url,
                "published_date": article.published_date.isoformat(),
                "content": input_content,
            },
            "response_schema": {
                "supporting_passages": ["exact passage"],
                "contradicting_passages": ["exact passage"],
                "date_passages": ["exact passage"],
                "proposed_claim": "string or null",
                "proposed_date": "ISO date or null",
            },
        }
        return json.dumps(data, ensure_ascii=True)

    @staticmethod
    def _string_list(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        return [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]

    @staticmethod
    def _optional_string(value: Any) -> Optional[str]:
        return value.strip() if isinstance(value, str) and value.strip() else None


class EventEvidenceVerifier:
    """Judge an event from traceable passages, independently of pass A's verdict."""

    def __init__(self, llm: StructuredLLM) -> None:
        self.llm = llm

    async def verify(
        self,
        event: Event,
        article: Article,
        extraction: EventEvidenceExtraction,
    ) -> EventEvidenceVerification:
        if not extraction.all_passages_traceable:
            return self._traceability_failure(event, article, extraction)

        payload = await self.llm.complete_json(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(event, article, extraction),
        )
        return EventEvidenceVerification(
            extraction_id=extraction.id,
            event_id=event.id,
            article_id=article.id,
            dataset_version=extraction.dataset_version,
            support=SupportLabel(payload.get("support", SupportLabel.NONE.value)),
            date_validity=DateLabel(
                payload.get("date_validity", DateLabel.UNCLEAR.value)
            ),
            entity_match=EntityLabel(
                payload.get("entity_match", EntityLabel.AMBIGUOUS.value)
            ),
            action=RepairAction(
                payload.get("action", RepairAction.DEFER_UNVERIFIABLE.value)
            ),
            confidence=float(payload.get("confidence", 0.0)),
            reason_codes=EventEvidenceExtractor._string_list(
                payload.get("reason_codes")
            ),
            notes=EventEvidenceExtractor._optional_string(payload.get("notes")),
            model=self.llm.model_name,
            prompt_version=VERIFIER_PROMPT_VERSION,
        )

    @staticmethod
    def _system_prompt() -> str:
        return """You independently verify an event-source pair using only the
provided exact passages. Assess source support, date validity, and entity match
separately. Choose one repair action: accept, revise, relink, reject, or
defer_unverifiable. Do not infer support from missing passages or use outside
knowledge. For date validity, use correct for the stated occurrence date or a
clear one-day timezone shift; near_match only for the same event within two
days due to delayed reporting or an imprecise stated date; incorrect for a
materially different date; and unclear when occurrence timing is not
established. Return JSON only."""

    @staticmethod
    def _user_prompt(
        event: Event,
        article: Article,
        extraction: EventEvidenceExtraction,
    ) -> str:
        data: Dict[str, Any] = {
            "event": {
                "title": event.title,
                "description": event.description,
                "occurred_date": event.occurred_date.isoformat()
                if event.occurred_date
                else None,
            },
            "article": {
                "title": article.title,
                "published_date": article.published_date.isoformat(),
            },
            "evidence": {
                "supporting_passages": extraction.supporting_passages,
                "contradicting_passages": extraction.contradicting_passages,
                "date_passages": extraction.date_passages,
            },
            "response_schema": {
                "support": "full|partial|none|contradictory",
                "date_validity": "correct|near_match|incorrect|unclear",
                "entity_match": "correct|ambiguous|incorrect",
                "action": "accept|revise|relink|reject|defer_unverifiable",
                "confidence": "number from 0 to 1",
                "reason_codes": ["short machine-readable code"],
                "notes": "brief explanation",
            },
        }
        return json.dumps(data, ensure_ascii=True)

    def _traceability_failure(
        self,
        event: Event,
        article: Article,
        extraction: EventEvidenceExtraction,
    ) -> EventEvidenceVerification:
        passages_were_untraceable = bool(extraction.traceability_failures)
        return EventEvidenceVerification(
            extraction_id=extraction.id,
            event_id=event.id,
            article_id=article.id,
            dataset_version=extraction.dataset_version,
            support=SupportLabel.NONE,
            date_validity=DateLabel.UNCLEAR,
            entity_match=EntityLabel.AMBIGUOUS,
            action=RepairAction.DEFER_UNVERIFIABLE,
            confidence=0.0,
            reason_codes=[
                "untraceable_extracted_passage"
                if passages_were_untraceable
                else "no_evidence_extracted"
            ],
            notes=(
                "Pass A returned text not found in the preserved snapshot."
                if passages_were_untraceable
                else "Pass A returned no supporting, contradicting, or date passages."
            ),
            model=TRACEABILITY_GATE_MODEL,
            prompt_version=(
                extraction.traceability_version or TRACEABILITY_VERSION
            ),
        )
