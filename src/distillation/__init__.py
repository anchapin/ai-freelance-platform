"""
Local Model Distillation Package

This package provides tools for capturing successful cloud model outputs
and preparing them for fine-tuning local models.

Components:
- data_collector: Captures successful GPT-4o outputs for distillation
- dataset_manager: Manages the curated dataset of high-quality examples

Usage:
    from src.distillation import DistillationDataCollector

    # Capture a successful task
    collector = DistillationDataCollector()
    collector.capture_success(
        prompt="...",
        response="...",
        domain="legal",
        task_type="document"
    )
"""

from .data_collector import DistillationDataCollector
from .dataset_manager import DistillationDatasetManager

__all__ = [
    "DistillationDataCollector",
    "DistillationDatasetManager",
]
