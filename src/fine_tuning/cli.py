"""
Fine-Tuning CLI Tool

Command-line interface for managing fine-tuning pipeline.
"""

import sys
import json
from typing import Optional
import logging

from .dataset_builder import DatasetBuilder, prepare_fine_tuning_dataset
from .openai_fine_tuner import OpenAIFineTuner
from .ollama_fine_tuner import OllamaFineTuner
from .model_evaluator import ModelEvaluator
from .ab_testing import ABTestFramework
from .model_registry import ModelRegistry
from .cost_tracker import CostTracker

logger = logging.getLogger(__name__)


class FineTuningCLI:
    """Command-line interface for fine-tuning pipeline."""

    def __init__(self):
        """Initialize CLI."""
        self.dataset_builder = DatasetBuilder()
        self.model_registry = ModelRegistry()
        self.cost_tracker = CostTracker()
        self.evaluator = ModelEvaluator()
        self.ab_test = ABTestFramework()

    def prepare_dataset(
        self,
        format: str = "openai",
        min_rating: int = 4,
        domain: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> str:
        """
        Prepare a fine-tuning dataset.

        Args:
            format: Dataset format (openai, alpaca, jsonl)
            min_rating: Minimum example rating
            domain: Optional domain filter
            output_dir: Output directory

        Returns:
            Path to dataset
        """
        print("Preparing fine-tuning dataset...")

        dataset_path = prepare_fine_tuning_dataset(
            output_dir=output_dir,
            format=format,
            min_rating=min_rating,
            domain=domain,
        )

        print(f"✓ Dataset prepared: {dataset_path}")
        return dataset_path

    def create_openai_job(
        self,
        model: str,
        training_file: str,
        suffix: Optional[str] = None,
        validation_file: Optional[str] = None,
    ) -> None:
        """
        Create an OpenAI fine-tuning job.

        Args:
            model: Base model (gpt-3.5-turbo or gpt-4o-mini)
            training_file: Path to training JSONL file
            suffix: Optional model suffix
            validation_file: Optional validation file
        """
        print(f"Creating OpenAI fine-tuning job for {model}...")

        tuner = OpenAIFineTuner()

        # Upload training file
        print("Uploading training file...")
        train_file_id = tuner.upload_training_file(training_file)

        validation_file_id = None
        if validation_file:
            print("Uploading validation file...")
            validation_file_id = tuner.upload_training_file(validation_file)

        # Create job
        job = tuner.create_fine_tuning_job(
            model=model,
            training_file_id=train_file_id,
            validation_file_id=validation_file_id,
            suffix=suffix,
        )

        print(f"✓ Job created: {job['job_id']}")
        print(f"  Status: {job['status']}")
        print(f"  Fine-tuned model: {job['fine_tuned_model']}")

    def check_openai_job_status(self, job_id: str) -> None:
        """
        Check status of OpenAI fine-tuning job.

        Args:
            job_id: Fine-tuning job ID
        """
        tuner = OpenAIFineTuner()
        status = tuner.get_job_status(job_id)

        print(f"Job: {job_id}")
        print(f"  Status: {status['status']}")
        print(f"  Model: {status['model']}")
        print(f"  Fine-tuned model: {status['fine_tuned_model']}")
        if status.get('trained_tokens'):
            print(f"  Trained tokens: {status['trained_tokens']}")

    def create_ollama_finetuning_script(
        self,
        base_model: str,
        dataset_file: str,
        output_model_name: str,
        num_epochs: int = 3,
    ) -> None:
        """
        Generate Ollama fine-tuning script.

        Args:
            base_model: Base model name
            dataset_file: Path to training dataset
            output_model_name: Name for fine-tuned model
            num_epochs: Number of epochs
        """
        print(f"Generating Ollama fine-tuning script...")

        tuner = OllamaFineTuner()

        # Generate script
        script_path = tuner.generate_unsloth_script(
            base_model=base_model,
            dataset_path=dataset_file,
            output_model_name=output_model_name,
            num_epochs=num_epochs,
        )

        print(f"✓ Script generated: {script_path}")
        print(f"\nTo run fine-tuning:")
        print(f"  python {script_path}")

    def evaluate_model(
        self,
        model_name: str,
        model_type: str,
        test_file: str,
        cost_per_inference: float = 0.0,
    ) -> None:
        """
        Evaluate a model on test set.

        Args:
            model_name: Model name
            model_type: Model type (base or fine_tuned)
            test_file: Path to test file (JSONL with predictions, references, latencies)
            cost_per_inference: Cost per inference
        """
        print(f"Evaluating {model_name}...")

        predictions = []
        references = []
        latencies = []

        try:
            with open(test_file, "r") as f:
                for line in f:
                    data = json.loads(line)
                    predictions.append(data.get("prediction", ""))
                    references.append(data.get("reference", ""))
                    latencies.append(data.get("latency_ms", 0))
        except FileNotFoundError:
            print(f"Error: Test file not found: {test_file}")
            return

        result = self.evaluator.evaluate_exact_match(
            predictions=predictions,
            references=references,
            model_name=model_name,
            model_type=model_type,
            latencies_ms=latencies,
            cost_per_inference=cost_per_inference,
        )

        print(f"✓ Evaluation complete")
        print(f"  Accuracy: {result.accuracy:.2%}")
        print(f"  Latency: {result.avg_latency_ms:.2f}ms")
        print(f"  Cost per inference: ${result.cost_per_inference:.6f}")

    def setup_ab_test(
        self,
        test_id: str,
        model_a: str,
        model_b: str,
    ) -> None:
        """
        Set up a new A/B test.

        Args:
            test_id: Test identifier
            model_a: Base model name
            model_b: Fine-tuned model name
        """
        print(f"Setting up A/B test: {test_id}")

        self.ab_test.create_test(test_id, model_a, model_b)
        print(f"✓ A/B test created: {test_id}")
        print(f"  Control (A): {model_a}")
        print(f"  Variant (B): {model_b}")

    def register_model(
        self,
        model_name: str,
        base_model: str,
        job_id: str,
        dataset_size: int,
        accuracy: Optional[float] = None,
        cost: float = 0.0,
    ) -> None:
        """
        Register a fine-tuned model.

        Args:
            model_name: Model name
            base_model: Base model
            job_id: Fine-tuning job ID
            dataset_size: Training dataset size
            accuracy: Model accuracy
            cost: Training cost
        """
        print(f"Registering model: {model_name}...")

        record = self.model_registry.register_model(
            model_name=model_name,
            base_model=base_model,
            job_id=job_id,
            dataset_size=dataset_size,
            accuracy=accuracy,
            cost=cost,
        )

        print(f"✓ Model registered: {model_name} v{record['version']}")
        if accuracy:
            print(f"  Accuracy: {accuracy:.2%}")
        print(f"  Training cost: ${cost:.2f}")

    def list_models(self) -> None:
        """List all registered models."""
        print("Registered Models:")
        print("-" * 70)

        stats = self.model_registry.get_registry_stats()
        print(f"Total models: {stats['total_models']}")
        print(f"Total versions: {stats['total_versions']}")
        print(f"Deployed: {stats['deployed_models']}")
        print(f"Total training cost: ${stats['total_training_cost']:.2f}")

        if self.model_registry.models:
            print("\nModels:")
            for model_name, versions in self.model_registry.models.items():
                latest = versions[-1]
                print(f"  {model_name}:")
                print(f"    Version: {latest['version']}")
                print(f"    Status: {latest['status']}")
                print(f"    Accuracy: {latest.get('accuracy', 'N/A')}")
                print(f"    Cost: ${latest.get('cost', 0):.2f}")

    def get_cost_summary(self) -> None:
        """Display cost summary."""
        print("Cost Summary:")
        print("-" * 70)

        summary = self.cost_tracker.get_cost_summary()

        print(f"Total training cost: ${summary['total_training_cost']:.2f}")
        print(f"Total inference cost: ${summary['total_inference_cost']:.2f}")
        print(f"Total cost: ${summary['total_cost']:.2f}")

        if summary["training_by_model"]:
            print("\nTraining by model:")
            for model, cost in summary["training_by_model"].items():
                print(f"  {model}: ${cost:.2f}")

        if summary["inference_by_model"]:
            print("\nInference by model:")
            for model, data in summary["inference_by_model"].items():
                print(f"  {model}: {data['count']} calls, ${data['total']:.2f}")

    def rollback_model(self, model_name: str, target_version: int) -> None:
        """
        Rollback to a previous model version.

        Args:
            model_name: Model name
            target_version: Target version
        """
        print(f"Rolling back {model_name} to v{target_version}...")

        success = self.model_registry.rollback_model(model_name, target_version)

        if success:
            print(f"✓ Rolled back {model_name} to v{target_version}")
        else:
            print(f"✗ Failed to rollback {model_name}")

    def auto_pipeline(
        self,
        base_model: str,
        domain: Optional[str] = None,
        suffix: Optional[str] = None,
    ) -> None:
        """
        Run end-to-end fine-tuning pipeline automatically.

        Args:
            base_model: Base model to fine-tune
            domain: Optional domain filter
            suffix: Optional model suffix
        """
        print(f"🚀 Starting automatic fine-tuning pipeline for {base_model}...")

        # 1. Prepare dataset
        dataset_path = self.prepare_dataset(format="openai", domain=domain)

        # 2. Create OpenAI job
        self.create_openai_job(
            model=base_model,
            training_file=dataset_path,
            suffix=suffix or f"{domain or 'general'}-auto",
        )

        print("\n✅ End-to-end pipeline initiated successfully!")
        print("Use 'ft-cli list-models' to track progress.")

    @staticmethod
    def print_help() -> None:
        """Print help message."""
        print("""
Fine-Tuning CLI Tool

Usage:
  ft-cli prepare-dataset [--format openai|alpaca|jsonl] [--min-rating 4] [--domain <domain>]
  ft-cli create-openai-job <model> <training_file> [--suffix <suffix>] [--validation-file <file>]
  ft-cli check-job-status <job_id>
  ft-cli create-ollama-script <base_model> <dataset_file> <output_model_name>
  ft-cli auto-pipeline <base_model> [--domain <domain>] [--suffix <suffix>]
  ft-cli evaluate-model <name> <type> <test_file> [--cost <cost>]
  ft-cli setup-ab-test <test_id> <model_a> <model_b>
  ft-cli register-model <name> <base_model> <job_id> <dataset_size> [--accuracy <accuracy>] [--cost <cost>]
  ft-cli list-models
  ft-cli cost-summary
  ft-cli rollback-model <model_name> <version>
  ft-cli help

Options:
  --format         Dataset format: openai, alpaca, jsonl (default: openai)
  --min-rating     Minimum rating for examples (1-5, default: 4)
  --domain         Filter by domain
  --cost           Cost per inference (USD)
  --accuracy       Model accuracy (0.0-1.0)
  --suffix         Model name suffix for OpenAI
  --validation-file Validation dataset file

Examples:
  ft-cli prepare-dataset --format openai --min-rating 4
  ft-cli create-openai-job gpt-3.5-turbo dataset.jsonl --suffix "v1"
  ft-cli check-job-status ftjob-abc123
  ft-cli register-model my-model gpt-3.5-turbo ftjob-abc123 500 --accuracy 0.95 --cost 0.002
  ft-cli list-models
  ft-cli cost-summary
""")


def main():
    """Main CLI entry point."""
    cli = FineTuningCLI()

    if len(sys.argv) < 2:
        FineTuningCLI.print_help()
        return

    command = sys.argv[1]

    try:
        if command == "help":
            FineTuningCLI.print_help()

        elif command == "prepare-dataset":
            kwargs = {}
            if "--format" in sys.argv:
                idx = sys.argv.index("--format")
                kwargs["format"] = sys.argv[idx + 1]
            if "--min-rating" in sys.argv:
                idx = sys.argv.index("--min-rating")
                kwargs["min_rating"] = int(sys.argv[idx + 1])
            if "--domain" in sys.argv:
                idx = sys.argv.index("--domain")
                kwargs["domain"] = sys.argv[idx + 1]

            cli.prepare_dataset(**kwargs)

        elif command == "create-openai-job":
            if len(sys.argv) < 4:
                print("Usage: ft-cli create-openai-job <model> <training_file>")
                return
            model = sys.argv[2]
            training_file = sys.argv[3]

            kwargs = {}
            if "--suffix" in sys.argv:
                idx = sys.argv.index("--suffix")
                kwargs["suffix"] = sys.argv[idx + 1]
            if "--validation-file" in sys.argv:
                idx = sys.argv.index("--validation-file")
                kwargs["validation_file"] = sys.argv[idx + 1]

            cli.create_openai_job(model, training_file, **kwargs)

        elif command == "check-job-status":
            if len(sys.argv) < 3:
                print("Usage: ft-cli check-job-status <job_id>")
                return
            cli.check_openai_job_status(sys.argv[2])

        elif command == "list-models":
            cli.list_models()

        elif command == "cost-summary":
            cli.get_cost_summary()

        elif command == "rollback-model":
            if len(sys.argv) < 4:
                print("Usage: ft-cli rollback-model <model_name> <version>")
                return
            cli.rollback_model(sys.argv[2], int(sys.argv[3]))

        elif command == "auto-pipeline":
            if len(sys.argv) < 3:
                print("Usage: ft-cli auto-pipeline <base_model>")
                return
            base_model = sys.argv[2]
            kwargs = {}
            if "--domain" in sys.argv:
                idx = sys.argv.index("--domain")
                kwargs["domain"] = sys.argv[idx + 1]
            if "--suffix" in sys.argv:
                idx = sys.argv.index("--suffix")
                kwargs["suffix"] = sys.argv[idx + 1]
            cli.auto_pipeline(base_model, **kwargs)

        else:
            print(f"Unknown command: {command}")
            FineTuningCLI.print_help()

    except Exception as e:
        print(f"Error: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
