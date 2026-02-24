"""
Distillation Dataset Manager

This module manages the curated dataset of high-quality examples for fine-tuning.
It provides utilities for filtering, validating, and preparing data for training.

Features:
- Load and filter examples by domain, rating, task type
- Validate dataset quality
- Prepare data in various formats for different fine-tuning frameworks
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable
from pathlib import Path


# Import configuration from data_collector
from .data_collector import (
    DISTILLATION_DIR,
    TEACHER_EXAMPLES_FILE,
    CURATED_DATASET_FILE,
    MIN_CURATION_RATING,
    MIN_EXAMPLES_FOR_TRAINING
)


class DistillationDatasetManager:
    """
    Manages the curated distillation dataset.
    
    Provides utilities for:
    - Loading and filtering examples
    - Validating dataset quality
    - Preparing data for training
    """
    
    def __init__(
        self,
        curated_file: Optional[str] = None,
        teacher_file: Optional[str] = None
    ):
        """
        Initialize the dataset manager.
        
        Args:
            curated_file: Path to curated dataset file
            teacher_file: Path to teacher examples file
        """
        self.curated_file = curated_file or CURATED_DATASET_FILE
        self.teacher_file = teacher_file or TEACHER_EXAMPLES_FILE
    
    def load_examples(
        self,
        filepath: Optional[str] = None,
        domain: Optional[str] = None,
        task_type: Optional[str] = None,
        min_rating: int = 1,
        max_rating: int = 5,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Load examples from the dataset with optional filters.
        
        Args:
            filepath: Path to JSONL file (defaults to curated)
            domain: Filter by domain
            task_type: Filter by task type
            min_rating: Minimum rating
            max_rating: Maximum rating
            limit: Maximum number of examples
            
        Returns:
            List of filtered examples
        """
        filepath = filepath or self.curated_file
        examples = []
        
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            record = json.loads(line)
                            
                            # Apply filters
                            if domain and record.get("domain") != domain:
                                continue
                            if task_type and record.get("task_type") != task_type:
                                continue
                            rating = record.get("rating", 0)
                            if rating < min_rating or rating > max_rating:
                                continue
                            
                            examples.append(record)
                            
                            if limit and len(examples) >= limit:
                                break
                        except json.JSONDecodeError:
                            continue
        except FileNotFoundError:
            pass
        
        return examples
    
    def validate_example(self, example: Dict[str, Any]) -> tuple:
        """
        Validate a single example for training quality.
        
        Args:
            example: The example to validate
            
        Returns:
            Tuple of (is_valid, issues_list)
        """
        issues = []
        
        # Check required fields
        required_fields = ["prompt", "response", "domain", "task_type"]
        for field in required_fields:
            if field not in example or not example[field]:
                issues.append(f"Missing required field: {field}")
        
        # Check prompt is not empty
        if "prompt" in example:
            if len(example["prompt"]) < 10:
                issues.append("Prompt too short")
        
        # Check response is not empty
        if "response" in example:
            if len(example["response"]) < 20:
                issues.append("Response too short")
        
        # Check rating is valid
        rating = example.get("rating", 0)
        if rating < 1 or rating > 5:
            issues.append("Invalid rating")
        
        return (len(issues) == 0, issues)
    
    def validate_dataset(
        self,
        filepath: Optional[str] = None,
        min_examples: int = MIN_EXAMPLES_FOR_TRAINING
    ) -> Dict[str, Any]:
        """
        Validate the entire dataset.
        
        Args:
            filepath: Path to dataset file
            min_examples: Minimum required examples
            
        Returns:
            Validation report
        """
        filepath = filepath or self.curated_file
        examples = self.load_examples(filepath)
        
        # Validate each example
        valid_examples = []
        invalid_examples = []
        
        for ex in examples:
            is_valid, issues = self.validate_example(ex)
            if is_valid:
                valid_examples.append(ex)
            else:
                invalid_examples.append({"example": ex, "issues": issues})
        
        # Calculate statistics
        total = len(examples)
        valid_count = len(valid_examples)
        invalid_count = len(invalid_examples)
        
        # Domain distribution
        domain_dist = {}
        for ex in valid_examples:
            domain = ex.get("domain", "unknown")
            domain_dist[domain] = domain_dist.get(domain, 0) + 1
        
        # Rating distribution
        rating_dist = {}
        for ex in valid_examples:
            rating = ex.get("rating", 0)
            rating_dist[rating] = rating_dist.get(rating, 0) + 1
        
        return {
            "total_examples": total,
            "valid_examples": valid_count,
            "invalid_examples": invalid_count,
            "validation_rate": valid_count / total if total > 0 else 0,
            "min_examples_required": min_examples,
            "has_enough_examples": valid_count >= min_examples,
            "domain_distribution": domain_dist,
            "rating_distribution": rating_dist,
            "invalid_details": invalid_examples[:10],  # First 10 invalid
            "is_valid": valid_count >= min_examples
        }
    
    def prepare_for_unsloth(
        self,
        output_path: Optional[str] = None,
        domain: Optional[str] = None,
        min_rating: int = MIN_CURATION_RATING
    ) -> str:
        """
        Prepare dataset for Unsloth fine-tuning.
        
        Args:
            output_path: Path for output file
            domain: Optional domain filter
            min_rating: Minimum rating
            
        Returns:
            Path to prepared dataset
        """
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(DISTILLATION_DIR, f"unsloth_train_{timestamp}.json")
        
        # Load examples
        examples = self.load_examples(
            domain=domain,
            min_rating=min_rating
        )
        
        # Convert to Alpaca format for Unsloth
        training_data = [
            {
                "instruction": ex["prompt"],
                "output": ex["response"],
                "input": ""
            }
            for ex in examples
        ]
        
        # Write to file
        with open(output_path, 'w') as f:
            json.dump(training_data, f, indent=2)
        
        return output_path
    
    def prepare_for_ollama(
        self,
        output_path: Optional[str] = None,
        domain: Optional[str] = None,
        min_rating: int = MIN_CURATION_RATING
    ) -> str:
        """
        Prepare dataset for Ollama fine-tuning.
        
        Args:
            output_path: Path for output file
            domain: Optional domain filter
            min_rating: Minimum rating
            
        Returns:
            Path to prepared dataset
        """
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(DISTILLATION_DIR, f"ollama_train_{timestamp}.jsonl")
        
        # Load examples
        examples = self.load_examples(
            domain=domain,
            min_rating=min_rating
        )
        
        # Convert to Ollama format (JSONL with prompt/completion)
        with open(output_path, 'w') as f:
            for ex in examples:
                ollama_example = {
                    "prompt": ex["prompt"],
                    "completion": ex["response"]
                }
                f.write(json.dumps(ollama_example) + '\n')
        
        return output_path
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive dataset statistics.
        
        Returns:
            Dictionary with statistics
        """
        # Load all examples
        curated = self.load_examples(self.curated_file)
        teacher = self.load_examples(self.teacher_file)
        
        # Calculate statistics
        return {
            "curated_count": len(curated),
            "teacher_count": len(teacher),
            "min_for_training": MIN_EXAMPLES_FOR_TRAINING,
            "ready_for_training": len(curated) >= MIN_EXAMPLES_FOR_TRAINING,
            "curated_by_domain": self._count_by_field(curated, "domain"),
            "curated_by_task_type": self._count_by_field(curated, "task_type"),
            "curated_by_rating": self._count_by_field(curated, "rating"),
            "avg_response_length": self._avg_field(curated, "response", lambda x: len(x)),
            "avg_prompt_length": self._avg_field(curated, "prompt", lambda x: len(x))
        }
    
    def _count_by_field(self, examples: List[Dict], field: str) -> Dict:
        """Count examples by a specific field."""
        counts = {}
        for ex in examples:
            value = ex.get(field, "unknown")
            counts[value] = counts.get(value, 0) + 1
        return counts
    
    def _avg_field(
        self,
        examples: List[Dict],
        field: str,
        transform: Callable = len
    ) -> float:
        """Calculate average of a field."""
        if not examples:
            return 0.0
        total = sum(transform(ex.get(field, "")) for ex in examples)
        return total / len(examples)
    
    def deduplicate(self, output_path: Optional[str] = None) -> int:
        """
        Remove duplicate examples based on prompt content.
        
        Args:
            output_path: Path for deduplicated file (defaults to overwriting curated)
            
        Returns:
            Number of duplicates removed
        """
        examples = self.load_examples(self.curated_file)
        
        # Deduplicate by prompt
        seen_prompts = set()
        unique_examples = []
        
        for ex in examples:
            # Normalize prompt for comparison
            prompt_normalized = ex.get("prompt", "").lower().strip()
            if prompt_normalized not in seen_prompts:
                seen_prompts.add(prompt_normalized)
                unique_examples.append(ex)
        
        duplicates_removed = len(examples) - len(unique_examples)
        
        # Write deduplicated data
        output_path = output_path or self.curated_file
        with open(output_path, 'w') as f:
            for ex in unique_examples:
                f.write(json.dumps(ex) + '\n')
        
        return duplicates_removed


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def get_dataset_stats() -> Dict[str, Any]:
    """Get dataset statistics."""
    manager = DistillationDatasetManager()
    return manager.get_statistics()


def validate_distillation_data() -> Dict[str, Any]:
    """Validate the distillation dataset."""
    manager = DistillationDatasetManager()
    return manager.validate_dataset()


def prepare_training_data(
    format: str = "unsloth",
    domain: Optional[str] = None
) -> str:
    """
    Prepare training data in the specified format.
    
    Args:
        format: Format type (unsloth, ollama, alpaca)
        domain: Optional domain filter
        
    Returns:
        Path to prepared dataset
    """
    manager = DistillationDatasetManager()
    
    if format == "unsloth":
        return manager.prepare_for_unsloth(domain=domain)
    elif format == "ollama":
        return manager.prepare_for_ollama(domain=domain)
    elif format == "alpaca":
        # Use data_collector for alpaca format
        from .data_collector import DistillationDataCollector
        collector = DistillationDataCollector()
        return collector.export_for_training(format="alpaca")
    else:
        raise ValueError(f"Unknown format: {format}")


if __name__ == "__main__":
    print("Distillation Dataset Manager")
    print("=" * 50)
    
    manager = DistillationDatasetManager()
    
    # Get statistics
    stats = manager.get_statistics()
    print(f"Curated examples: {stats['curated_count']}")
    print(f"Teacher examples: {stats['teacher_count']}")
    print(f"Ready for training: {stats['ready_for_training']}")
    print(f"By domain: {stats['curated_by_domain']}")
    print(f"By task type: {stats['curated_by_task_type']}")
    print(f"By rating: {stats['curated_by_rating']}")
    print(f"Avg prompt length: {stats['avg_prompt_length']:.0f}")
    print(f"Avg response length: {stats['avg_response_length']:.0f}")
    
    # Validate
    print("\nValidation:")
    validation = manager.validate_dataset()
    print(f"Valid examples: {validation['valid_examples']}")
    print(f"Invalid examples: {validation['invalid_examples']}")
    print(f"Is valid: {validation['is_valid']}")
