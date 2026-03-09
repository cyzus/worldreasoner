"""API routes for auto-benchmark results and conditions."""

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from src.domain.evaluation.conditions import EXPERIMENT_CONDITIONS
from src.utils.logging import logger

router = APIRouter()

BENCHMARKS_DIR = Path("benchmarks")


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
            return json.load(f)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read benchmark result: {e}"
        )


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
