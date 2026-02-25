"""
Fine-Tuning Pipeline for Custom Models

This module provides a comprehensive fine-tuning pipeline for task-specific models,
including dataset preparation, training, evaluation, A/B testing, and versioning.

Features:
- Fine-tuning data preparation from task history
- Support for OpenAI API and local Ollama fine-tuning
- Dataset builder with quality filtering
- Fine-tuned model evaluation (accuracy, cost/latency)
- A/B testing framework for model comparison
- Automated retraining on new data
- Model versioning and rollback
- Cost tracking and ROI calculation
"""

from .dataset_builder import DatasetBuilder, prepare_fine_tuning_dataset
from .openai_fine_tuner import OpenAIFineTuner
from .ollama_fine_tuner import OllamaFineTuner
from .model_evaluator import ModelEvaluator, EvaluationResult
from .ab_testing import ABTestFramework, ABTestResult
from .model_registry import ModelRegistry, FinetuneJobRecord
from .cost_tracker import CostTracker, CostAnalysis
from .cli import FineTuningCLI

__all__ = [
    "DatasetBuilder",
    "prepare_fine_tuning_dataset",
    "OpenAIFineTuner",
    "OllamaFineTuner",
    "ModelEvaluator",
    "EvaluationResult",
    "ABTestFramework",
    "ABTestResult",
    "ModelRegistry",
    "FinetuneJobRecord",
    "CostTracker",
    "CostAnalysis",
    "FineTuningCLI",
]
