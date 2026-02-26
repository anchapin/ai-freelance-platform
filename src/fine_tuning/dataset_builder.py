"""
Dataset Builder for Fine-Tuning

Prepares training data from task history and distillation data.
Supports multiple formats and quality filtering.
"""

import os
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)


class DatasetBuilder:
    """
    Builds fine-tuning datasets from task history and distillation data.

    Features:
    - Load examples from distillation collector
    - Filter by domain, task type, rating
    - Validate quality and completeness
    - Export in multiple formats (Alpaca, OpenAI, JSONL)
    - Data augmentation and splitting
    """

    def __init__(self, output_dir: Optional[str] = None):
        """
        Initialize the dataset builder.

        Args:
            output_dir: Directory to save datasets
        """
        self.output_dir = output_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data",
            "fine_tuning",
        )
        os.makedirs(self.output_dir, exist_ok=True)

    def build_from_distillation(
        self,
        min_rating: int = 4,
        domain: Optional[str] = None,
        task_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Build dataset from distillation data collector.

        Args:
            min_rating: Minimum rating (1-5) to include
            domain: Optional domain filter
            task_type: Optional task type filter
            limit: Maximum number of examples

        Returns:
            List of training examples
        """
        try:
            from ..distillation.data_collector import DistillationDataCollector

            collector = DistillationDataCollector()
            examples = collector.get_curated_examples(
                domain=domain, min_rating=min_rating, limit=limit
            )

            # Filter by task_type if specified
            if task_type:
                examples = [e for e in examples if e.get("task_type") == task_type]

            logger.info(
                f"Loaded {len(examples)} distillation examples "
                f"(rating>={min_rating}, domain={domain}, task_type={task_type})"
            )
            return examples
        except Exception as e:
            logger.error(f"Failed to load distillation data: {e}")
            return []

    def validate_examples(self, examples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate dataset examples for completeness and quality.

        Args:
            examples: List of examples to validate

        Returns:
            Validation report with statistics
        """
        required_fields = ["prompt", "response"]
        valid_examples = []
        invalid_examples = []

        for ex in examples:
            issues = []

            # Check required fields
            for field in required_fields:
                if field not in ex or not ex[field]:
                    issues.append(f"Missing {field}")

            # Check minimum lengths
            prompt = ex.get("prompt", "")
            if not prompt or len(str(prompt)) < 10:
                issues.append("Prompt too short")
            response = ex.get("response", "")
            if not response or len(str(response)) < 20:
                issues.append("Response too short")

            if issues:
                invalid_examples.append({"example": ex, "issues": issues})
            else:
                valid_examples.append(ex)

        return {
            "total": len(examples),
            "valid": len(valid_examples),
            "invalid": len(invalid_examples),
            "valid_examples": valid_examples,
            "invalid_examples": invalid_examples,
            "validation_rate": len(valid_examples) / len(examples) if examples else 0,
        }

    def to_openai_format(self, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert examples to OpenAI fine-tuning format.

        Args:
            examples: List of examples

        Returns:
            Examples in OpenAI format
        """
        formatted = []
        for ex in examples:
            formatted.append(
                {
                    "messages": [
                        {"role": "user", "content": ex.get("prompt", "")},
                        {"role": "assistant", "content": ex.get("response", "")},
                    ]
                }
            )
        return formatted

    def to_alpaca_format(self, examples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert examples to Alpaca fine-tuning format.

        Args:
            examples: List of examples

        Returns:
            Examples in Alpaca format
        """
        return [
            {"instruction": ex.get("prompt", ""), "output": ex.get("response", ""), "input": ""}
            for ex in examples
        ]

    def to_jsonl_format(self, examples: List[Dict[str, Any]]) -> str:
        """
        Convert examples to JSONL format.

        Args:
            examples: List of examples

        Returns:
            JSONL formatted string
        """
        lines = [json.dumps(ex) for ex in examples]
        return "\n".join(lines)

    def split_train_test(
        self, examples: List[Dict[str, Any]], train_ratio: float = 0.8
    ) -> tuple:
        """
        Split examples into train and test sets.

        Args:
            examples: List of examples
            train_ratio: Ratio of training data (default 0.8)

        Returns:
            Tuple of (train_examples, test_examples)
        """
        split_idx = int(len(examples) * train_ratio)
        return examples[:split_idx], examples[split_idx:]

    def save_dataset(
        self,
        examples: List[Dict[str, Any]],
        filename: str,
        format: str = "openai",
    ) -> str:
        """
        Save dataset to file in specified format.

        Args:
            examples: List of examples
            filename: Output filename (without extension)
            format: Format type (openai, alpaca, jsonl)

        Returns:
            Path to saved file
        """
        if format == "openai":
            formatted = self.to_openai_format(examples)
            ext = ".jsonl"
        elif format == "alpaca":
            formatted = self.to_alpaca_format(examples)
            ext = ".json"
        elif format == "jsonl":
            formatted = examples
            ext = ".jsonl"
        else:
            raise ValueError(f"Unknown format: {format}")

        filepath = os.path.join(self.output_dir, f"{filename}{ext}")

        if ext == ".json":
            with open(filepath, "w") as f:
                json.dump(formatted, f, indent=2)
        else:  # JSONL format
            with open(filepath, "w") as f:
                for item in formatted:
                    f.write(json.dumps(item) + "\n")

        logger.info(f"Saved {len(examples)} examples to {filepath}")
        return filepath

    def get_dataset_stats(self, examples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get statistics about the dataset.

        Args:
            examples: List of examples

        Returns:
            Statistics dictionary
        """
        domains = {}
        task_types = {}
        ratings = {}

        for ex in examples:
            domain = ex.get("domain", "unknown")
            domains[domain] = domains.get(domain, 0) + 1

            task_type = ex.get("task_type", "unknown")
            task_types[task_type] = task_types.get(task_type, 0) + 1

            rating = ex.get("rating", 0)
            ratings[rating] = ratings.get(rating, 0) + 1

        # Calculate average lengths
        avg_prompt_len = (
            sum(len(ex.get("prompt", "")) for ex in examples) / len(examples)
            if examples
            else 0
        )
        avg_response_len = (
            sum(len(ex.get("response", "")) for ex in examples) / len(examples)
            if examples
            else 0
        )

        return {
            "total_examples": len(examples),
            "domains": domains,
            "task_types": task_types,
            "ratings": ratings,
            "avg_prompt_length": avg_prompt_len,
            "avg_response_length": avg_response_len,
        }


def prepare_fine_tuning_dataset(
    output_dir: Optional[str] = None,
    format: str = "openai",
    min_rating: int = 4,
    domain: Optional[str] = None,
) -> str:
    """
    Convenience function to prepare a complete fine-tuning dataset.

    Args:
        output_dir: Directory to save dataset
        format: Output format (openai, alpaca, jsonl)
        min_rating: Minimum example rating
        domain: Optional domain filter

    Returns:
        Path to saved dataset
    """
    builder = DatasetBuilder(output_dir)
    examples = builder.build_from_distillation(min_rating=min_rating, domain=domain)

    if not examples:
        raise ValueError("No training examples found with given criteria")

    validation = builder.validate_examples(examples)
    logger.info(f"Validation: {validation['valid']}/{validation['total']} valid")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"dataset_{domain or 'all'}_{timestamp}"

    return builder.save_dataset(validation["valid_examples"], filename, format=format)
