"""
Fine-Tuned Model Evaluator

Evaluates model performance on test sets and compares metrics.
"""

import json
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    """Results from model evaluation."""

    model_name: str
    model_type: str  # "base" or "fine_tuned"
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    avg_latency_ms: float
    cost_per_inference: float
    timestamp: str
    test_set_size: int
    metadata: Dict[str, Any]


class ModelEvaluator:
    """
    Evaluates fine-tuned models on test sets.

    Metrics:
    - Accuracy, Precision, Recall, F1
    - Latency (average inference time)
    - Cost per inference
    - Comparison between base and fine-tuned
    """

    def __init__(self):
        """Initialize the evaluator."""
        self.results: List[EvaluationResult] = []

    def evaluate_exact_match(
        self,
        predictions: List[str],
        references: List[str],
        model_name: str,
        model_type: str = "base",
        latencies_ms: Optional[List[float]] = None,
        cost_per_inference: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """
        Evaluate model using exact match accuracy.

        Args:
            predictions: List of model predictions
            references: List of reference answers
            model_name: Name of model being evaluated
            model_type: "base" or "fine_tuned"
            latencies_ms: Optional list of latencies per prediction
            cost_per_inference: Cost per inference call
            metadata: Additional metadata

        Returns:
            EvaluationResult
        """
        if len(predictions) != len(references):
            raise ValueError(
                f"Predictions ({len(predictions)}) and references "
                f"({len(references)}) must have same length"
            )

        # Calculate exact match accuracy
        correct = sum(1 for p, r in zip(predictions, references) if p.strip() == r.strip())
        accuracy = correct / len(predictions) if predictions else 0.0

        # For exact match, precision and recall same as accuracy
        precision = accuracy
        recall = accuracy
        f1_score = accuracy

        # Calculate average latency
        avg_latency_ms = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0

        result = EvaluationResult(
            model_name=model_name,
            model_type=model_type,
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            avg_latency_ms=avg_latency_ms,
            cost_per_inference=cost_per_inference,
            timestamp=datetime.now(timezone.utc).isoformat(),
            test_set_size=len(predictions),
            metadata=metadata or {},
        )

        self.results.append(result)
        logger.info(f"Evaluated {model_name}: accuracy={accuracy:.2%}")
        return result

    def evaluate_substring_match(
        self,
        predictions: List[str],
        references: List[str],
        model_name: str,
        model_type: str = "base",
        latencies_ms: Optional[List[float]] = None,
        cost_per_inference: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """
        Evaluate model using substring matching.

        Counts a prediction as correct if reference contains prediction as substring.

        Args:
            predictions: List of model predictions
            references: List of reference answers
            model_name: Name of model being evaluated
            model_type: "base" or "fine_tuned"
            latencies_ms: Optional list of latencies per prediction
            cost_per_inference: Cost per inference call
            metadata: Additional metadata

        Returns:
            EvaluationResult
        """
        if len(predictions) != len(references):
            raise ValueError(
                f"Predictions ({len(predictions)}) and references "
                f"({len(references)}) must have same length"
            )

        # Calculate substring match accuracy
        correct = sum(
            1
            for p, r in zip(predictions, references)
            if p.strip().lower() in r.strip().lower()
        )
        accuracy = correct / len(predictions) if predictions else 0.0

        # For substring match, precision and recall same as accuracy
        precision = accuracy
        recall = accuracy
        f1_score = accuracy

        # Calculate average latency
        avg_latency_ms = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0

        result = EvaluationResult(
            model_name=model_name,
            model_type=model_type,
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1_score,
            avg_latency_ms=avg_latency_ms,
            cost_per_inference=cost_per_inference,
            timestamp=datetime.now(timezone.utc).isoformat(),
            test_set_size=len(predictions),
            metadata=metadata or {},
        )

        self.results.append(result)
        logger.info(f"Evaluated {model_name}: substring_accuracy={accuracy:.2%}")
        return result

    def compare_models(
        self, base_result: EvaluationResult, finetuned_result: EvaluationResult
    ) -> Dict[str, Any]:
        """
        Compare base and fine-tuned models.

        Args:
            base_result: Evaluation result for base model
            finetuned_result: Evaluation result for fine-tuned model

        Returns:
            Comparison dictionary with deltas
        """
        accuracy_improvement = (
            finetuned_result.accuracy - base_result.accuracy
        )
        latency_improvement = base_result.avg_latency_ms - finetuned_result.avg_latency_ms
        cost_improvement = base_result.cost_per_inference - finetuned_result.cost_per_inference

        return {
            "base_model": base_result.model_name,
            "finetuned_model": finetuned_result.model_name,
            "accuracy_delta": accuracy_improvement,
            "accuracy_improvement_pct": (
                accuracy_improvement / base_result.accuracy * 100
                if base_result.accuracy > 0
                else 0
            ),
            "latency_delta_ms": latency_improvement,
            "latency_improvement_pct": (
                latency_improvement / base_result.avg_latency_ms * 100
                if base_result.avg_latency_ms > 0
                else 0
            ),
            "cost_delta": cost_improvement,
            "cost_improvement_pct": (
                cost_improvement / base_result.cost_per_inference * 100
                if base_result.cost_per_inference > 0
                else 0
            ),
            "base_metrics": asdict(base_result),
            "finetuned_metrics": asdict(finetuned_result),
        }

    def calculate_roi(
        self,
        base_cost: float,
        finetuned_cost: float,
        accuracy_improvement: float,
        inference_count: int,
    ) -> Dict[str, float]:
        """
        Calculate ROI of fine-tuning.

        Args:
            base_cost: Cost per inference for base model
            finetuned_cost: Cost per inference for fine-tuned model
            accuracy_improvement: Absolute accuracy improvement (0.0-1.0)
            inference_count: Expected number of inferences

        Returns:
            ROI metrics
        """
        total_base_cost = base_cost * inference_count
        total_finetuned_cost = finetuned_cost * inference_count

        cost_savings = total_base_cost - total_finetuned_cost

        # Value of accuracy improvement (reduced errors/rework)
        # Assume each error costs $10
        error_cost = 10
        value_from_improvement = accuracy_improvement * inference_count * error_cost

        total_roi = cost_savings + value_from_improvement

        return {
            "inference_count": inference_count,
            "total_base_cost": total_base_cost,
            "total_finetuned_cost": total_finetuned_cost,
            "cost_savings": cost_savings,
            "accuracy_improvement": accuracy_improvement,
            "value_from_improvement": value_from_improvement,
            "total_roi": total_roi,
            "payback_period_inferences": (
                inference_count if total_roi > 0 else float("inf")
            ),
        }

    def get_results_summary(self) -> Dict[str, Any]:
        """
        Get summary of all evaluation results.

        Returns:
            Summary dictionary
        """
        if not self.results:
            return {
                "total_evaluations": 0,
                "models": {},
            }

        # Group by model
        by_model = {}
        for result in self.results:
            if result.model_name not in by_model:
                by_model[result.model_name] = []
            by_model[result.model_name].append(result)

        summary = {
            "total_evaluations": len(self.results),
            "models": {},
        }

        for model_name, results in by_model.items():
            latest = results[-1]
            summary["models"][model_name] = {
                "model_type": latest.model_type,
                "latest_accuracy": latest.accuracy,
                "latest_latency_ms": latest.avg_latency_ms,
                "latest_cost": latest.cost_per_inference,
                "evaluation_count": len(results),
                "timestamp": latest.timestamp,
            }

        return summary

    def export_results(self, filepath: str) -> None:
        """
        Export evaluation results to JSON file.

        Args:
            filepath: Path to save results
        """
        results_data = [asdict(r) for r in self.results]
        with open(filepath, "w") as f:
            json.dump(results_data, f, indent=2)
        logger.info(f"Exported {len(self.results)} evaluation results to {filepath}")
