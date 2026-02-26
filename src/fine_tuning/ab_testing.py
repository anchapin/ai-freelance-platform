"""
A/B Testing Framework for Fine-Tuned Models

Compare fine-tuned models against base models in production.
"""

import json
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ABTestStatus(str, Enum):
    """Status of A/B test."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class ABTestResult:
    """Result from A/B test."""

    test_id: str
    model_a: str  # Base model
    model_b: str  # Fine-tuned model
    status: str
    total_samples: int
    model_a_accuracy: float
    model_b_accuracy: float
    accuracy_improvement: float
    model_a_avg_latency: float
    model_b_avg_latency: float
    latency_improvement: float
    model_a_cost_per_inference: float
    model_b_cost_per_inference: float
    cost_improvement: float
    statistical_significance: bool
    confidence_level: float
    started_at: str
    completed_at: str
    metadata: Dict[str, Any]


class ABTestFramework:
    """
    A/B testing framework for comparing models.

    Features:
    - Traffic splitting between models
    - Real-time metric collection
    - Statistical significance testing
    - Automatic winner detection
    """

    def __init__(self):
        """Initialize A/B testing framework."""
        self.tests: Dict[str, ABTestResult] = {}
        self.ongoing_tests: Dict[str, Dict[str, Any]] = {}

    def create_test(
        self,
        test_id: str,
        model_a: str,
        model_b: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new A/B test.

        Args:
            test_id: Unique test identifier
            model_a: Base model name (control)
            model_b: Fine-tuned model name (variant)
            metadata: Additional test metadata

        Returns:
            Test configuration
        """
        test_config = {
            "test_id": test_id,
            "model_a": model_a,
            "model_b": model_b,
            "status": ABTestStatus.PENDING,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "samples": {"model_a": [], "model_b": []},
            "metadata": metadata or {},
        }

        self.ongoing_tests[test_id] = test_config
        logger.info(f"Created A/B test: {test_id} ({model_a} vs {model_b})")
        return test_config

    def record_sample(
        self,
        test_id: str,
        model: str,
        prediction: str,
        reference: str,
        latency_ms: float,
        cost: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Record a sample in the A/B test.

        Args:
            test_id: Test ID
            model: "model_a" or "model_b"
            prediction: Model's prediction
            reference: Ground truth reference
            latency_ms: Inference latency
            cost: Inference cost
            metadata: Additional metadata

        Returns:
            True if recorded successfully
        """
        if test_id not in self.ongoing_tests:
            logger.error(f"Test {test_id} not found")
            return False

        test = self.ongoing_tests[test_id]

        # Verify model assignment
        if model == "model_a":
            actual_model = test["model_a"]
        elif model == "model_b":
            actual_model = test["model_b"]
        else:
            logger.error(f"Invalid model: {model}")
            return False

        # Check if prediction matches reference
        is_correct = prediction.strip() == reference.strip()

        sample = {
            "prediction": prediction,
            "reference": reference,
            "correct": is_correct,
            "latency_ms": latency_ms,
            "cost": cost,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        test["samples"][model].append(sample)
        logger.debug(f"Recorded sample for {actual_model} in test {test_id}")
        return True

    def conclude_test(
        self,
        test_id: str,
        alpha: float = 0.05,
    ) -> ABTestResult:
        """
        Conclude an A/B test and compute results.

        Uses chi-squared test for statistical significance.

        Args:
            test_id: Test ID
            alpha: Significance level (default 0.05)

        Returns:
            Test result
        """
        if test_id not in self.ongoing_tests:
            raise ValueError(f"Test {test_id} not found")

        test = self.ongoing_tests[test_id]

        # Extract samples
        samples_a = test["samples"]["model_a"]
        samples_b = test["samples"]["model_b"]

        if not samples_a or not samples_b:
            raise ValueError(f"Test {test_id} has incomplete samples")

        # Calculate metrics
        accuracy_a = (
            sum(1 for s in samples_a if s["correct"]) / len(samples_a)
            if samples_a
            else 0.0
        )
        accuracy_b = (
            sum(1 for s in samples_b if s["correct"]) / len(samples_b)
            if samples_b
            else 0.0
        )

        latency_a = sum(s["latency_ms"] for s in samples_a) / len(samples_a) if samples_a else 0.0
        latency_b = sum(s["latency_ms"] for s in samples_b) / len(samples_b) if samples_b else 0.0

        cost_a = sum(s["cost"] for s in samples_a) / len(samples_a) if samples_a else 0.0
        cost_b = sum(s["cost"] for s in samples_b) / len(samples_b) if samples_b else 0.0

        # Chi-squared test for statistical significance
        is_significant = self._chi_squared_test(
            accuracy_a, accuracy_b, len(samples_a), len(samples_b), alpha
        )

        result = ABTestResult(
            test_id=test_id,
            model_a=test["model_a"],
            model_b=test["model_b"],
            status=ABTestStatus.COMPLETED.value,
            total_samples=len(samples_a) + len(samples_b),
            model_a_accuracy=accuracy_a,
            model_b_accuracy=accuracy_b,
            accuracy_improvement=accuracy_b - accuracy_a,
            model_a_avg_latency=latency_a,
            model_b_avg_latency=latency_b,
            latency_improvement=latency_a - latency_b,
            model_a_cost_per_inference=cost_a,
            model_b_cost_per_inference=cost_b,
            cost_improvement=cost_a - cost_b,
            statistical_significance=is_significant,
            confidence_level=1.0 - alpha,
            started_at=test["started_at"],
            completed_at=datetime.now(timezone.utc).isoformat(),
            metadata=test["metadata"],
        )

        self.tests[test_id] = result
        del self.ongoing_tests[test_id]

        logger.info(
            f"Concluded test {test_id}: "
            f"accuracy {accuracy_a:.2%} vs {accuracy_b:.2%}, "
            f"significant={is_significant}"
        )

        return result

    def _chi_squared_test(
        self, accuracy_a: float, accuracy_b: float, n_a: int, n_b: int, alpha: float = 0.05
    ) -> bool:
        """
        Perform chi-squared test for statistical significance.

        Args:
            accuracy_a: Accuracy of model A
            accuracy_b: Accuracy of model B
            n_a: Number of samples for model A
            n_b: Number of samples for model B
            alpha: Significance level

        Returns:
            True if difference is statistically significant
        """
        from math import sqrt

        # Calculate proportions
        p1 = accuracy_a
        p2 = accuracy_b
        n1 = n_a
        n2 = n_b

        # Pooled proportion
        p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)

        # Standard error
        se = sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))

        # Z-score
        z = (p2 - p1) / se if se > 0 else 0

        # For alpha=0.05 (two-tailed), critical z ≈ 1.96
        critical_z = 1.96

        return abs(z) > critical_z

    def get_test_results(self, test_id: str) -> Optional[ABTestResult]:
        """
        Get results of a completed test.

        Args:
            test_id: Test ID

        Returns:
            Test result or None if not found
        """
        return self.tests.get(test_id)

    def get_all_results(self) -> List[ABTestResult]:
        """
        Get all completed test results.

        Returns:
            List of test results
        """
        return list(self.tests.values())

    def recommend_winner(self, test_result: ABTestResult) -> str:
        """
        Recommend a winner based on test results.

        Args:
            test_result: A/B test result

        Returns:
            Name of recommended model
        """
        if not test_result.statistical_significance:
            return "TIE (not statistically significant)"

        # Weighted scoring: 60% accuracy, 20% latency, 20% cost
        score_a = (
            test_result.model_a_accuracy * 0.6
            - (test_result.model_a_avg_latency / 1000) * 0.2
            - test_result.model_a_cost_per_inference * 0.2
        )

        score_b = (
            test_result.model_b_accuracy * 0.6
            - (test_result.model_b_avg_latency / 1000) * 0.2
            - test_result.model_b_cost_per_inference * 0.2
        )

        if score_b > score_a:
            return test_result.model_b
        else:
            return test_result.model_a

    def export_results(self, filepath: str) -> None:
        """
        Export all test results to JSON file.

        Args:
            filepath: Path to save results
        """
        results_data = [asdict(r) for r in self.tests.values()]
        with open(filepath, "w") as f:
            json.dump(results_data, f, indent=2)
        logger.info(f"Exported {len(self.tests)} A/B test results to {filepath}")
