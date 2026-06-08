"""API routes for auto-benchmark results and conditions."""

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from src.config.settings import get_config
from src.core.llm import get_knowledge_cutoff_date
from src.domain.evaluation.conditions import EXPERIMENT_CONDITIONS
from src.utils.logging import logger

router = APIRouter()

BENCHMARKS_DIR = Path("experiments/benchmarks")


@router.get("/results")
async def list_benchmark_results() -> List[Dict[str, Any]]:
    """List saved benchmark result files from benchmarks/ directory."""
    if not BENCHMARKS_DIR.exists():
        return []

    results = []
    for path in sorted(BENCHMARKS_DIR.glob("*.json"), reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            info = data.get("auto_benchmark_info", {})
            config = data.get("configuration", {})

            results.append(
                {
                    "run_id": info.get("run_id", path.stem),
                    "timestamp": info.get("timestamp", ""),
                    "duration_seconds": info.get("duration_seconds", 0),
                    "conditions": config.get("conditions", []),
                    "models": config.get("models", []),
                    "question_count": config.get("question_count", 0),
                }
            )
        except Exception as e:
            logger.warning(f"Failed to read benchmark file {path}: {e}")
            continue

    return results


def _normalize_model_name(name: str) -> str:
    """Strip whitespace and normalize routing/proxy prefixes.

    - litellm_proxy/ and litellm/ are always stripped (they wrap real model ids)
    - dashscope/deepseek-* -> deepseek/deepseek-* (DashScope was used as a proxy)
    - dashscope/qwen* stays as-is (dashscope is the canonical provider for Qwen)
    """
    name = name.strip()
    for prefix in ("litellm_proxy/", "litellm/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    # DashScope used as proxy for DeepSeek models
    if name.startswith("dashscope/deepseek"):
        name = "deepseek/" + name[len("dashscope/"):]
    return name


def _normalize_condition_results(condition_results: dict) -> dict:
    """Normalize model names in condition_results, merging duplicate keys."""
    normalized: dict = {}
    for cond, model_map in condition_results.items():
        normalized[cond] = {}
        for model, cell in model_map.items():
            key = _normalize_model_name(model)
            if key not in normalized[cond]:
                normalized[cond][key] = cell
            else:
                # Merge: keep the cell with more successful forecasts
                existing = normalized[cond][key]
                if cell.get("successful", 0) > existing.get("successful", 0):
                    normalized[cond][key] = cell
    return normalized


@router.get("/results/{run_id}")
async def get_benchmark_result(run_id: str) -> Dict[str, Any]:
    """Get full result JSON for a specific benchmark run."""
    path = BENCHMARKS_DIR / f"{run_id}.json"
    if not path.exists():
        raise HTTPException(
            status_code=404, detail=f"Benchmark run '{run_id}' not found"
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "condition_results" in data:
            data["condition_results"] = _normalize_condition_results(
                data["condition_results"]
            )
        return data
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read benchmark result: {e}"
        )


@router.get("/results/{run_id}/filtered")
async def get_benchmark_result_filtered(run_id: str) -> Dict[str, Any]:
    """Re-aggregate a benchmark run with contamination filtering applied.

    Excludes (model, question) pairs where the question's estimated_start_time
    falls before the model's knowledge cutoff date — matching the paper's
    reporting methodology.

    Returns the same shape as GET /results/{run_id} but with condition_results
    recomputed on the clean subset, plus a 'contamination_summary' field
    showing how many forecasts were excluded per (condition, model).
    """
    path = BENCHMARKS_DIR / f"{run_id}.json"
    if not path.exists():
        raise HTTPException(
            status_code=404, detail=f"Benchmark run '{run_id}' not found"
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Normalize model names before filtering
        if "condition_results" in data:
            data["condition_results"] = _normalize_condition_results(
                data["condition_results"]
            )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read benchmark result: {e}"
        )

    # Load question estimated_start_time from DB
    try:
        import sqlite3
        cfg = get_config()
        conn = sqlite3.connect(str(cfg.database.db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, estimated_start_time FROM questions"
        ).fetchall()
        conn.close()
        q_start: Dict[str, Optional[str]] = {
            r["id"]: r["estimated_start_time"] for r in rows
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to load question start times from DB: {e}",
        )

    contamination_summary: Dict[str, Dict[str, int]] = {}

    # Re-aggregate each (condition, model) cell using only clean forecasts
    filtered_condition_results: Dict[str, Dict[str, Any]] = {}

    for cond_name, model_map in data.get("condition_results", {}).items():
        filtered_condition_results[cond_name] = {}
        contamination_summary[cond_name] = {}

        for model_name, cell in model_map.items():
            detailed = cell.get("detailed_results") or []
            if not detailed:
                # No per-forecast data — can't filter, keep as-is
                filtered_condition_results[cond_name][model_name] = cell
                contamination_summary[cond_name][model_name] = 0
                continue

            # Get model cutoff once
            cutoff_str = get_knowledge_cutoff_date(model_name)
            cutoff_dt: Optional[datetime] = None
            if cutoff_str and cutoff_str != "Unknown":
                try:
                    cutoff_dt = datetime.fromisoformat(cutoff_str).replace(
                        tzinfo=timezone.utc
                    )
                except ValueError:
                    pass

            # Filter forecasts
            clean = []
            excluded = 0
            for r in detailed:
                if r.get("status") != "success":
                    continue
                qid = r.get("question_id", "")
                start_str = q_start.get(qid)

                if cutoff_dt and start_str:
                    try:
                        start_dt = datetime.fromisoformat(
                            start_str.replace("Z", "+00:00")
                        )
                        if start_dt.tzinfo is None:
                            start_dt = start_dt.replace(tzinfo=timezone.utc)
                        if start_dt < cutoff_dt:
                            excluded += 1
                            continue
                    except ValueError:
                        pass

                clean.append(r)

            contamination_summary[cond_name][model_name] = excluded

            if not clean:
                filtered_condition_results[cond_name][model_name] = {
                    **cell,
                    "successful": 0,
                    "total_questions": 0,
                    "accuracy": None,
                    "avg_brier_score": None,
                    "avg_log_score": None,
                }
                continue

            # Re-compute metrics on clean set
            correct = sum(1 for r in clean if r.get("is_correct"))
            brier_vals = [r["brier_score"] for r in clean if r.get("brier_score") is not None]
            log_vals = [r["log_score"] for r in clean if r.get("log_score") is not None]

            filtered_condition_results[cond_name][model_name] = {
                **cell,
                "successful": len(clean),
                "total_questions": len(clean),
                "accuracy": correct / len(clean),
                "avg_brier_score": (
                    statistics.mean(brier_vals) if brier_vals else None
                ),
                "avg_log_score": (
                    statistics.mean(log_vals) if log_vals else None
                ),
                # Keep detailed_results so the per-run table still works
                "detailed_results": clean,
            }

    return {
        **data,
        "condition_results": filtered_condition_results,
        "contamination_filtered": True,
        "contamination_summary": contamination_summary,
    }


@router.get("/conditions")
async def list_conditions() -> List[Dict[str, Any]]:
    """List available experiment conditions."""
    return [
        {
            "name": cond.name.value,
            "display_name": cond.display_name,
            "mode": cond.mode,
            "enable_causal_tools": cond.enable_causal_tools,
            "is_oracle": cond.is_oracle,
            "max_steps": cond.max_steps,
            "description": cond.description,
        }
        for cond in EXPERIMENT_CONDITIONS.values()
    ]
