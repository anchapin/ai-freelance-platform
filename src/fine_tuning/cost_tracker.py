"""
Cost Tracking and ROI Analysis

Tracks costs of fine-tuning and inference to calculate ROI.
"""

import json
import os
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


@dataclass
class CostAnalysis:
    """Cost analysis results."""

    model_name: str
    training_cost: float
    training_tokens: int
    inference_cost_per_call: float
    expected_inferences: int
    total_inference_cost: float
    total_cost: float
    break_even_inferences: int
    roi_at_expected: float
    payback_days: float


class CostTracker:
    """
    Tracks and analyzes costs for fine-tuning and inference.

    Features:
    - Cost per training job
    - Cost per inference call
    - ROI calculation
    - Break-even analysis
    - Cost projections
    """

    def __init__(self, tracker_path: Optional[str] = None):
        """
        Initialize cost tracker.

        Args:
            tracker_path: Path to cost tracking file
        """
        if tracker_path is None:
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data",
                "fine_tuning",
            )
            os.makedirs(data_dir, exist_ok=True)
            tracker_path = os.path.join(data_dir, "cost_tracking.json")

        self.tracker_path = tracker_path
        self.costs: Dict[str, Any] = self._load_costs()

    def _load_costs(self) -> Dict[str, Any]:
        """Load cost tracking data."""
        if os.path.exists(self.tracker_path):
            try:
                with open(self.tracker_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load costs: {e}")
                return {"jobs": {}, "inferences": []}
        return {"jobs": {}, "inferences": []}

    def _save_costs(self) -> None:
        """Save cost tracking data."""
        with open(self.tracker_path, "w") as f:
            json.dump(self.costs, f, indent=2)

    def record_training_job(
        self,
        job_id: str,
        model_name: str,
        base_model: str,
        dataset_size: int,
        training_tokens: int,
        total_cost: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a training job cost.

        Args:
            job_id: Training job ID
            model_name: Fine-tuned model name
            base_model: Base model name
            dataset_size: Number of training examples
            training_tokens: Total training tokens
            total_cost: Total training cost
            metadata: Additional metadata
        """
        job_record = {
            "job_id": job_id,
            "model_name": model_name,
            "base_model": base_model,
            "dataset_size": dataset_size,
            "training_tokens": training_tokens,
            "total_cost": total_cost,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        self.costs["jobs"][job_id] = job_record
        self._save_costs()

        logger.info(f"Recorded training cost for {job_id}: ${total_cost:.4f}")

    def record_inference(
        self,
        model_name: str,
        tokens_used: int,
        cost: float,
        is_fine_tuned: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record an inference call cost.

        Args:
            model_name: Model name
            tokens_used: Tokens used in inference
            cost: Cost of inference
            is_fine_tuned: Whether model is fine-tuned
            metadata: Additional metadata
        """
        inference_record = {
            "model_name": model_name,
            "tokens_used": tokens_used,
            "cost": cost,
            "is_fine_tuned": is_fine_tuned,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        self.costs["inferences"].append(inference_record)
        self._save_costs()

    def get_job_cost(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cost of a specific training job.

        Args:
            job_id: Training job ID

        Returns:
            Job cost record or None
        """
        return self.costs["jobs"].get(job_id)

    def get_model_training_cost(self, model_name: str) -> float:
        """
        Get total training cost for a model.

        Args:
            model_name: Model name

        Returns:
            Total training cost
        """
        total = 0.0
        for job in self.costs["jobs"].values():
            if job.get("model_name") == model_name:
                total += job.get("total_cost", 0)
        return total

    def get_inference_costs(
        self, model_name: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Get inference costs by model.

        Args:
            model_name: Optional specific model

        Returns:
            Inference costs dictionary
        """
        costs = {}

        for inference in self.costs["inferences"]:
            model = inference.get("model_name", "unknown")

            if model_name and model != model_name:
                continue

            if model not in costs:
                costs[model] = {"count": 0, "total": 0.0}

            costs[model]["count"] += 1
            costs[model]["total"] += inference.get("cost", 0)

        return costs

    def calculate_roi(
        self,
        model_name: str,
        base_model_inference_cost: float,
        expected_inference_count: int,
        cost_per_error: float = 10.0,
    ) -> CostAnalysis:
        """
        Calculate ROI for a fine-tuned model.

        Args:
            model_name: Fine-tuned model name
            base_model_inference_cost: Cost per inference for base model
            expected_inference_count: Expected number of inferences
            cost_per_error: Estimated cost per error

        Returns:
            Cost analysis with ROI
        """
        training_cost = self.get_model_training_cost(model_name)

        # Get fine-tuned model inference cost
        inference_costs = self.get_inference_costs(model_name)
        if model_name in inference_costs:
            finetuned_cost_data = inference_costs[model_name]
            finetuned_inference_cost = (
                finetuned_cost_data["total"] / finetuned_cost_data["count"]
                if finetuned_cost_data["count"] > 0
                else base_model_inference_cost
            )
        else:
            finetuned_inference_cost = base_model_inference_cost * 0.5  # Assume 50% cost reduction

        # Calculate total costs
        total_base_cost = base_model_inference_cost * expected_inference_count
        total_finetuned_cost = training_cost + (
            finetuned_inference_cost * expected_inference_count
        )

        # Cost savings from inference
        cost_savings = total_base_cost - (finetuned_inference_cost * expected_inference_count)

        # Break-even point
        if cost_savings > 0:
            break_even = int(training_cost / cost_savings * expected_inference_count)
        else:
            break_even = float("inf")

        # ROI calculation
        roi = (cost_savings - training_cost) / training_cost if training_cost > 0 else 0

        # Estimate payback period (in days)
        daily_savings = cost_savings / 30  # Assume spread over month
        payback_days = training_cost / daily_savings if daily_savings > 0 else float("inf")

        return CostAnalysis(
            model_name=model_name,
            training_cost=training_cost,
            training_tokens=self.costs["jobs"]
            .get(
                next(
                    (j for j in self.costs["jobs"] if self.costs["jobs"][j].get("model_name") == model_name),
                    None,
                ),
                {},
            )
            .get("training_tokens", 0),
            inference_cost_per_call=finetuned_inference_cost,
            expected_inferences=expected_inference_count,
            total_inference_cost=finetuned_inference_cost * expected_inference_count,
            total_cost=total_finetuned_cost,
            break_even_inferences=break_even,
            roi_at_expected=roi,
            payback_days=payback_days,
        )

    def get_cost_summary(self) -> Dict[str, Any]:
        """
        Get overall cost summary.

        Returns:
            Cost summary dictionary
        """
        training_costs = {}
        for job_id, job in self.costs["jobs"].items():
            model_name = job.get("model_name", "unknown")
            if model_name not in training_costs:
                training_costs[model_name] = 0.0
            training_costs[model_name] += job.get("total_cost", 0)

        inference_costs = self.get_inference_costs()

        total_training = sum(training_costs.values())
        total_inference = sum(
            data["total"] for data in inference_costs.values()
        )

        return {
            "total_training_cost": total_training,
            "total_inference_cost": total_inference,
            "total_cost": total_training + total_inference,
            "training_by_model": training_costs,
            "inference_by_model": {
                model: {"count": data["count"], "total": data["total"]}
                for model, data in inference_costs.items()
            },
        }

    def export_costs(self, filepath: str) -> None:
        """
        Export cost tracking data.

        Args:
            filepath: Path to export
        """
        with open(filepath, "w") as f:
            json.dump(self.costs, f, indent=2)
        logger.info(f"Exported cost tracking data to {filepath}")
