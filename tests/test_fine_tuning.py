"""
Tests for Fine-Tuning Pipeline

Tests cover:
- Dataset preparation and validation
- Fine-tuning job creation and management
- Model evaluation metrics
- A/B testing framework
- Model versioning and registry
- Cost tracking and ROI
"""

import pytest
import os
import json
import tempfile
from typing import List, Dict, Any
from datetime import datetime, timezone

from src.fine_tuning.dataset_builder import DatasetBuilder
from src.fine_tuning.model_evaluator import ModelEvaluator, EvaluationResult
from src.fine_tuning.ab_testing import ABTestFramework, ABTestResult
from src.fine_tuning.model_registry import ModelRegistry
from src.fine_tuning.cost_tracker import CostTracker


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_examples() -> List[Dict[str, Any]]:
    """Sample training examples."""
    return [
        {
            "prompt": "Write a function to sort a list",
            "response": "def sort_list(lst): return sorted(lst)",
            "domain": "coding",
            "task_type": "code_generation",
            "rating": 5,
        },
        {
            "prompt": "Create a bar chart for sales data",
            "response": "import matplotlib.pyplot as plt\nplt.bar(x, y)\nplt.show()",
            "domain": "data_analysis",
            "task_type": "visualization",
            "rating": 5,
        },
        {
            "prompt": "Summarize this document",
            "response": "The document discusses...",
            "domain": "text",
            "task_type": "summarization",
            "rating": 4,
        },
        {
            "prompt": "Calculate the ROI",
            "response": "ROI = (Revenue - Cost) / Cost * 100",
            "domain": "finance",
            "task_type": "calculation",
            "rating": 4,
        },
    ]


@pytest.fixture
def dataset_builder(temp_data_dir):
    """Create dataset builder with temp directory."""
    return DatasetBuilder(output_dir=temp_data_dir)


@pytest.fixture
def model_registry(temp_data_dir):
    """Create model registry with temp path."""
    registry_path = os.path.join(temp_data_dir, "registry.json")
    return ModelRegistry(registry_path=registry_path)


@pytest.fixture
def cost_tracker(temp_data_dir):
    """Create cost tracker with temp path."""
    tracker_path = os.path.join(temp_data_dir, "costs.json")
    return CostTracker(tracker_path=tracker_path)


# ============================================================================
# DATASET BUILDER TESTS
# ============================================================================


class TestDatasetBuilder:
    """Test dataset builder functionality."""

    def test_validate_examples_success(self, dataset_builder, sample_examples):
        """Test validation of valid examples."""
        result = dataset_builder.validate_examples(sample_examples)

        assert result["total"] == 4
        assert result["valid"] == 4
        assert result["invalid"] == 0
        assert result["validation_rate"] == 1.0

    def test_validate_examples_with_invalid(self, dataset_builder):
        """Test validation with invalid examples."""
        examples = [
            {"prompt": "Valid prompt", "response": "Valid response with enough content"},
            {"prompt": "Short", "response": "Short"},  # Both too short
            {"prompt": "Valid prompt 2", "response": None},  # Missing response
        ]

        result = dataset_builder.validate_examples(examples)

        assert result["total"] == 3
        assert result["valid"] == 1
        assert result["invalid"] == 2

    def test_to_openai_format(self, dataset_builder, sample_examples):
        """Test conversion to OpenAI format."""
        formatted = dataset_builder.to_openai_format(sample_examples)

        assert len(formatted) == 4
        for item in formatted:
            assert "messages" in item
            assert len(item["messages"]) == 2
            assert item["messages"][0]["role"] == "user"
            assert item["messages"][1]["role"] == "assistant"

    def test_to_alpaca_format(self, dataset_builder, sample_examples):
        """Test conversion to Alpaca format."""
        formatted = dataset_builder.to_alpaca_format(sample_examples)

        assert len(formatted) == 4
        for item in formatted:
            assert "instruction" in item
            assert "output" in item
            assert "input" in item
            assert item["input"] == ""

    def test_to_jsonl_format(self, dataset_builder, sample_examples):
        """Test conversion to JSONL format."""
        jsonl_str = dataset_builder.to_jsonl_format(sample_examples)

        lines = jsonl_str.split("\n")
        # Should have 4 lines (plus possibly empty last line)
        non_empty_lines = [l for l in lines if l.strip()]
        assert len(non_empty_lines) == 4

        # Each line should be valid JSON
        for line in non_empty_lines:
            data = json.loads(line)
            assert "prompt" in data or "messages" in data

    def test_split_train_test(self, dataset_builder, sample_examples):
        """Test train/test split."""
        train, test = dataset_builder.split_train_test(sample_examples, train_ratio=0.75)

        assert len(train) == 3
        assert len(test) == 1
        assert len(train) + len(test) == 4

    def test_save_dataset_openai_format(self, dataset_builder, sample_examples, temp_data_dir):
        """Test saving dataset in OpenAI format."""
        filepath = dataset_builder.save_dataset(
            sample_examples, "test_openai_dataset", format="openai"
        )

        assert os.path.exists(filepath)
        assert filepath.endswith(".jsonl")

        # Verify content
        with open(filepath, "r") as f:
            lines = f.readlines()
            assert len(lines) == 4
            for line in lines:
                data = json.loads(line)
                assert "messages" in data

    def test_save_dataset_alpaca_format(self, dataset_builder, sample_examples, temp_data_dir):
        """Test saving dataset in Alpaca format."""
        filepath = dataset_builder.save_dataset(
            sample_examples, "test_alpaca_dataset", format="alpaca"
        )

        assert os.path.exists(filepath)
        assert filepath.endswith(".json")

        # Verify content
        with open(filepath, "r") as f:
            data = json.load(f)
            assert len(data) == 4
            for item in data:
                assert "instruction" in item
                assert "output" in item

    def test_get_dataset_stats(self, dataset_builder, sample_examples):
        """Test dataset statistics calculation."""
        stats = dataset_builder.get_dataset_stats(sample_examples)

        assert stats["total_examples"] == 4
        assert len(stats["domains"]) == 4
        assert len(stats["task_types"]) == 4
        assert stats["domains"]["coding"] == 1
        assert stats["domains"]["data_analysis"] == 1
        assert stats["avg_prompt_length"] > 0
        assert stats["avg_response_length"] > 0


# ============================================================================
# MODEL EVALUATOR TESTS
# ============================================================================


class TestModelEvaluator:
    """Test model evaluation functionality."""

    def test_evaluate_exact_match(self):
        """Test exact match evaluation."""
        evaluator = ModelEvaluator()

        predictions = ["hello", "world", "test"]
        references = ["hello", "world", "test"]
        latencies = [100, 120, 110]

        result = evaluator.evaluate_exact_match(
            predictions=predictions,
            references=references,
            model_name="test-model",
            model_type="base",
            latencies_ms=latencies,
            cost_per_inference=0.001,
        )

        assert result.accuracy == 1.0
        assert result.precision == 1.0
        assert result.recall == 1.0
        assert result.f1_score == 1.0
        assert result.avg_latency_ms == 110.0
        assert result.cost_per_inference == 0.001
        assert result.test_set_size == 3

    def test_evaluate_exact_match_with_errors(self):
        """Test exact match with some errors."""
        evaluator = ModelEvaluator()

        predictions = ["hello", "world", "wrong"]
        references = ["hello", "there", "test"]

        result = evaluator.evaluate_exact_match(
            predictions=predictions,
            references=references,
            model_name="test-model",
            model_type="fine_tuned",
            latencies_ms=[100, 100, 100],
        )

        assert result.accuracy == 1 / 3
        assert result.test_set_size == 3

    def test_evaluate_substring_match(self):
        """Test substring match evaluation."""
        evaluator = ModelEvaluator()

        predictions = ["hello world", "testing", "code"]
        references = ["hello world is great", "testing is fun", "python code"]

        result = evaluator.evaluate_substring_match(
            predictions=predictions,
            references=references,
            model_name="test-model",
            model_type="base",
            latencies_ms=[100, 100, 100],
        )

        assert result.accuracy == 1.0
        assert result.test_set_size == 3

    def test_compare_models(self):
        """Test model comparison."""
        evaluator = ModelEvaluator()

        base_result = EvaluationResult(
            model_name="base-gpt35",
            model_type="base",
            accuracy=0.85,
            precision=0.85,
            recall=0.85,
            f1_score=0.85,
            avg_latency_ms=200.0,
            cost_per_inference=0.002,
            timestamp=datetime.now(timezone.utc).isoformat(),
            test_set_size=100,
            metadata={},
        )

        finetuned_result = EvaluationResult(
            model_name="finetuned-gpt35",
            model_type="fine_tuned",
            accuracy=0.92,
            precision=0.92,
            recall=0.92,
            f1_score=0.92,
            avg_latency_ms=150.0,
            cost_per_inference=0.0015,
            timestamp=datetime.now(timezone.utc).isoformat(),
            test_set_size=100,
            metadata={},
        )

        comparison = evaluator.compare_models(base_result, finetuned_result)

        assert comparison["accuracy_delta"] == pytest.approx(0.07)
        assert comparison["latency_delta_ms"] == 50.0
        assert comparison["cost_delta"] == pytest.approx(0.0005)
        assert comparison["accuracy_improvement_pct"] > 0

    def test_calculate_roi(self):
        """Test ROI calculation."""
        evaluator = ModelEvaluator()

        roi = evaluator.calculate_roi(
            base_cost=0.002,
            finetuned_cost=0.001,
            accuracy_improvement=0.05,
            inference_count=10000,
        )

        assert roi["inference_count"] == 10000
        assert roi["cost_savings"] > 0
        assert roi["value_from_improvement"] > 0
        assert roi["total_roi"] > 0

    def test_get_results_summary(self):
        """Test results summary."""
        evaluator = ModelEvaluator()

        # Add some results
        evaluator.evaluate_exact_match(
            predictions=["a", "b"], references=["a", "b"],
            model_name="model1", model_type="base", latencies_ms=[100, 100]
        )

        evaluator.evaluate_exact_match(
            predictions=["x", "y"], references=["x", "y"],
            model_name="model2", model_type="fine_tuned", latencies_ms=[90, 85]
        )

        summary = evaluator.get_results_summary()

        assert summary["total_evaluations"] == 2
        assert "model1" in summary["models"]
        assert "model2" in summary["models"]


# ============================================================================
# A/B TESTING TESTS
# ============================================================================


class TestABTestFramework:
    """Test A/B testing framework."""

    def test_create_test(self):
        """Test A/B test creation."""
        ab_test = ABTestFramework()

        config = ab_test.create_test(
            test_id="test_001",
            model_a="base-model",
            model_b="finetuned-model",
        )

        assert config["test_id"] == "test_001"
        assert config["model_a"] == "base-model"
        assert config["model_b"] == "finetuned-model"

    def test_record_sample(self):
        """Test recording A/B test samples."""
        ab_test = ABTestFramework()

        ab_test.create_test("test_001", "model_a", "model_b")

        # Record samples for model A
        success_a = ab_test.record_sample(
            test_id="test_001",
            model="model_a",
            prediction="hello",
            reference="hello",
            latency_ms=100,
            cost=0.001,
        )

        assert success_a is True

        # Record samples for model B
        success_b = ab_test.record_sample(
            test_id="test_001",
            model="model_b",
            prediction="hello",
            reference="hello",
            latency_ms=90,
            cost=0.0008,
        )

        assert success_b is True

    def test_record_sample_invalid_test(self):
        """Test recording sample with invalid test ID."""
        ab_test = ABTestFramework()

        success = ab_test.record_sample(
            test_id="nonexistent",
            model="model_a",
            prediction="hello",
            reference="hello",
            latency_ms=100,
            cost=0.001,
        )

        assert success is False

    def test_conclude_test(self):
        """Test concluding A/B test."""
        ab_test = ABTestFramework()

        ab_test.create_test("test_001", "base-model", "finetuned-model")

        # Record 100 samples for each model
        for i in range(100):
            # Model A: 85% accuracy
            is_correct_a = i < 85
            ab_test.record_sample(
                test_id="test_001",
                model="model_a",
                prediction=f"pred_{i}" if is_correct_a else "wrong",
                reference=f"pred_{i}",
                latency_ms=200,
                cost=0.002,
            )

            # Model B: 92% accuracy
            is_correct_b = i < 92
            ab_test.record_sample(
                test_id="test_001",
                model="model_b",
                prediction=f"pred_{i}" if is_correct_b else "wrong",
                reference=f"pred_{i}",
                latency_ms=150,
                cost=0.0015,
            )

        result = ab_test.conclude_test("test_001")

        assert isinstance(result, ABTestResult)
        assert result.model_a_accuracy == pytest.approx(0.85)
        assert result.model_b_accuracy == pytest.approx(0.92)
        assert result.total_samples == 200

    def test_chi_squared_test(self):
        """Test chi-squared significance test."""
        ab_test = ABTestFramework()

        # Large difference (significant)
        is_sig_large = ab_test._chi_squared_test(0.50, 0.70, 1000, 1000)
        assert is_sig_large is True

        # Small difference (not significant)
        is_sig_small = ab_test._chi_squared_test(0.50, 0.51, 50, 50)
        assert is_sig_small is False

    def test_recommend_winner(self):
        """Test winner recommendation."""
        ab_test = ABTestFramework()

        result = ABTestResult(
            test_id="test_001",
            model_a="base",
            model_b="finetuned",
            status="COMPLETED",
            total_samples=200,
            model_a_accuracy=0.85,
            model_b_accuracy=0.92,
            accuracy_improvement=0.07,
            model_a_avg_latency=200.0,
            model_b_avg_latency=150.0,
            latency_improvement=50.0,
            model_a_cost_per_inference=0.002,
            model_b_cost_per_inference=0.0015,
            cost_improvement=0.0005,
            statistical_significance=True,
            confidence_level=0.95,
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            metadata={},
        )

        winner = ab_test.recommend_winner(result)
        assert winner == "finetuned"


# ============================================================================
# MODEL REGISTRY TESTS
# ============================================================================


class TestModelRegistry:
    """Test model registry functionality."""

    def test_register_model(self, model_registry):
        """Test registering a model."""
        record = model_registry.register_model(
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-123",
            dataset_size=500,
            accuracy=0.95,
            cost=50.0,
        )

        assert record["version"] == 1
        assert record["model_name"] == "my-model"
        assert record["accuracy"] == 0.95
        assert record["status"] == "READY"

    def test_register_multiple_versions(self, model_registry):
        """Test registering multiple versions."""
        # Register v1
        model_registry.register_model(
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-123",
            dataset_size=500,
            accuracy=0.95,
        )

        # Register v2
        model_registry.register_model(
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-124",
            dataset_size=600,
            accuracy=0.96,
        )

        versions = model_registry.list_model_versions("my-model")
        assert len(versions) == 2
        assert versions[0]["version"] == 1
        assert versions[1]["version"] == 2
        assert versions[1]["accuracy"] == 0.96

    def test_get_model_version(self, model_registry):
        """Test getting specific model version."""
        model_registry.register_model(
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-123",
            dataset_size=500,
            accuracy=0.95,
        )

        # Get latest
        latest = model_registry.get_model_version("my-model")
        assert latest["version"] == 1

        # Get specific version
        v1 = model_registry.get_model_version("my-model", version=1)
        assert v1["version"] == 1

    def test_set_model_status(self, model_registry):
        """Test updating model status."""
        model_registry.register_model(
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-123",
            dataset_size=500,
        )

        success = model_registry.set_model_status("my-model", "DEPLOYED")
        assert success is True

        record = model_registry.get_model_version("my-model")
        assert record["status"] == "DEPLOYED"
        assert record["deployed_at"] is not None

    def test_rollback_model(self, model_registry):
        """Test model rollback."""
        # Register two versions
        model_registry.register_model(
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-123",
            dataset_size=500,
            accuracy=0.95,
        )

        model_registry.register_model(
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-124",
            dataset_size=600,
            accuracy=0.90,  # Worse accuracy
        )

        # Deploy v2, then rollback
        model_registry.set_model_status("my-model", "DEPLOYED")
        success = model_registry.rollback_model("my-model", 1)

        assert success is True

        versions = model_registry.list_model_versions("my-model")
        assert versions[0]["status"] == "DEPLOYED"  # v1 deployed
        assert versions[1]["status"] == "ARCHIVED"  # v2 archived

    def test_get_deployment_status(self, model_registry):
        """Test getting deployment status."""
        model_registry.register_model(
            model_name="model-1",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-123",
            dataset_size=500,
        )

        model_registry.set_model_status("model-1", "DEPLOYED")

        deployed = model_registry.get_deployment_status()

        assert "model-1" in deployed
        assert deployed["model-1"]["version"] == 1

    def test_get_cost_summary(self, model_registry):
        """Test cost summary."""
        model_registry.register_model(
            model_name="model-1",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-123",
            dataset_size=500,
            cost=50.0,
        )

        model_registry.register_model(
            model_name="model-2",
            base_model="gpt-4o-mini",
            job_id="ftjob-124",
            dataset_size=600,
            cost=100.0,
        )

        summary = model_registry.get_cost_summary()

        assert summary["total_cost"] == 150.0
        assert summary["models"]["model-1"]["cost"] == 50.0
        assert summary["models"]["model-2"]["cost"] == 100.0


# ============================================================================
# COST TRACKER TESTS
# ============================================================================


class TestCostTracker:
    """Test cost tracking functionality."""

    def test_record_training_job(self, cost_tracker):
        """Test recording training job cost."""
        cost_tracker.record_training_job(
            job_id="ftjob-123",
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            dataset_size=500,
            training_tokens=100000,
            total_cost=50.0,
        )

        job_cost = cost_tracker.get_job_cost("ftjob-123")
        assert job_cost["total_cost"] == 50.0
        assert job_cost["training_tokens"] == 100000

    def test_record_inference(self, cost_tracker):
        """Test recording inference cost."""
        cost_tracker.record_inference(
            model_name="my-model",
            tokens_used=500,
            cost=0.001,
            is_fine_tuned=True,
        )

        inferences = cost_tracker.get_inference_costs("my-model")
        assert "my-model" in inferences
        assert inferences["my-model"]["count"] == 1
        assert inferences["my-model"]["total"] == 0.001

    def test_get_model_training_cost(self, cost_tracker):
        """Test getting model training cost."""
        cost_tracker.record_training_job(
            job_id="ftjob-123",
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            dataset_size=500,
            training_tokens=100000,
            total_cost=50.0,
        )

        cost_tracker.record_training_job(
            job_id="ftjob-124",
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            dataset_size=600,
            training_tokens=120000,
            total_cost=60.0,
        )

        total_cost = cost_tracker.get_model_training_cost("my-model")
        assert total_cost == 110.0

    def test_calculate_roi(self, cost_tracker):
        """Test ROI calculation."""
        cost_tracker.record_training_job(
            job_id="ftjob-123",
            model_name="my-model",
            base_model="gpt-3.5-turbo",
            dataset_size=500,
            training_tokens=100000,
            total_cost=50.0,
        )

        # Record some inferences
        for _ in range(100):
            cost_tracker.record_inference(
                model_name="my-model",
                tokens_used=500,
                cost=0.0008,
                is_fine_tuned=True,
            )

        roi = cost_tracker.calculate_roi(
            model_name="my-model",
            base_model_inference_cost=0.001,
            expected_inference_count=10000,
        )

        assert roi.model_name == "my-model"
        assert roi.training_cost == 50.0
        assert roi.expected_inferences == 10000

    def test_get_cost_summary(self, cost_tracker):
        """Test cost summary."""
        cost_tracker.record_training_job(
            job_id="ftjob-123",
            model_name="model-1",
            base_model="gpt-3.5-turbo",
            dataset_size=500,
            training_tokens=100000,
            total_cost=50.0,
        )

        cost_tracker.record_inference(
            model_name="model-1",
            tokens_used=500,
            cost=0.001,
            is_fine_tuned=True,
        )

        summary = cost_tracker.get_cost_summary()

        assert summary["total_training_cost"] == 50.0
        assert summary["total_inference_cost"] == 0.001
        assert summary["total_cost"] == 50.001


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestFineTuningIntegration:
    """Integration tests for fine-tuning pipeline."""

    def test_full_pipeline(
        self, dataset_builder, model_registry, cost_tracker, sample_examples
    ):
        """Test full fine-tuning pipeline."""
        # Step 1: Prepare dataset
        validation = dataset_builder.validate_examples(sample_examples)
        assert validation["valid"] == 4

        # Step 2: Register model
        model_record = model_registry.register_model(
            model_name="test-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-123",
            dataset_size=len(validation["valid_examples"]),
            accuracy=0.92,
            cost=50.0,
        )

        assert model_record["version"] == 1

        # Step 3: Record training cost
        cost_tracker.record_training_job(
            job_id="ftjob-123",
            model_name="test-model",
            base_model="gpt-3.5-turbo",
            dataset_size=len(validation["valid_examples"]),
            training_tokens=100000,
            total_cost=50.0,
        )

        # Step 4: Deploy model
        model_registry.set_model_status("test-model", "DEPLOYED")

        # Verify everything is connected
        deployed = model_registry.get_deployment_status()
        assert "test-model" in deployed

        cost_summary = cost_tracker.get_cost_summary()
        assert cost_summary["total_training_cost"] == 50.0

    def test_model_improvement_scenario(self, model_registry, cost_tracker):
        """Test scenario where fine-tuned model improves over time."""
        # Register base model
        model_registry.register_model(
            model_name="improvement-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-100",
            dataset_size=500,
            accuracy=0.85,
            cost=50.0,
        )

        # v1 deployed but not great
        model_registry.set_model_status("improvement-model", "DEPLOYED")

        # Register improved v2
        model_registry.register_model(
            model_name="improvement-model",
            base_model="gpt-3.5-turbo",
            job_id="ftjob-101",
            dataset_size=600,
            accuracy=0.92,
            cost=60.0,
        )

        # Deploy v2
        model_registry.rollback_model("improvement-model", 2)
        model_registry.set_model_status("improvement-model", "DEPLOYED", version=2)

        # Check improvement
        versions = model_registry.list_model_versions("improvement-model")
        assert versions[1]["accuracy"] > versions[0]["accuracy"]
        assert len(versions) == 2


# ============================================================================
# RUN TESTS
# ============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
