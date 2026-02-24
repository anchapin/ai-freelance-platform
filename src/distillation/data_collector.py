"""
Distillation Data Collector

This module captures successful outputs from cloud models (GPT-4o) for use
in fine-tuning local models. It stores prompt-response pairs with metadata
to a JSONL dataset for later curation and training.

The concept:
- Every time GPT-4o generates a perfect script for a complex task,
  save the prompt and generated code to a local .jsonl dataset
- Once you have 500+ highly rated examples, use Unsloth to fine-tune
- Update TASK_MODEL_MAP to route to your fine-tuned local model
"""

import os
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path


# =============================================================================
# CONFIGURATION
# =============================================================================

# Default paths for dataset storage
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DISTILLATION_DIR = os.path.join(PROJECT_ROOT, "data", "distillation")
TEACHER_EXAMPLES_FILE = os.path.join(DISTILLATION_DIR, "teacher_examples.jsonl")
CURATED_DATASET_FILE = os.path.join(DISTILLATION_DIR, "curated_dataset.jsonl")

# Minimum rating to include in curated dataset
MIN_CURATION_RATING = 4  # 1-5 scale

# Minimum examples before training is recommended
MIN_EXAMPLES_FOR_TRAINING = 500


class DistillationDataCollector:
    """
    Captures successful cloud model outputs for distillation.
    
    This collector should be called whenever:
    - A task completes successfully using GPT-4o (cloud model)
    - The output quality is high (passed review, positive feedback)
    
    It stores these examples for later fine-tuning.
    """
    
    def __init__(
        self,
        output_dir: Optional[str] = None,
        teacher_file: Optional[str] = None,
        curated_file: Optional[str] = None
    ):
        """
        Initialize the data collector.
        
        Args:
            output_dir: Base directory for dataset storage
            teacher_file: Path to teacher examples JSONL file
            curated_file: Path to curated dataset JSONL file
        """
        # Set up paths
        self.output_dir = output_dir or DISTILLATION_DIR
        self.teacher_file = teacher_file or TEACHER_EXAMPLES_FILE
        self.curated_file = curated_file or CURATED_DATASET_FILE
        
        # Ensure directory exists
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Ensure files exist (create if not)
        if not os.path.exists(self.teacher_file):
            with open(self.teacher_file, 'w') as f:
                pass  # Create empty file
        
        if not os.path.exists(self.curated_file):
            with open(self.curated_file, 'w') as f:
                pass  # Create empty file
    
    def capture_success(
        self,
        prompt: str,
        response: str,
        domain: str,
        task_type: str,
        rating: int = 5,
        metadata: Optional[Dict[str, Any]] = None,
        model_used: str = "gpt-4o"
    ) -> str:
        """
        Capture a successful task completion for distillation.
        
        This should be called when:
        - A task completes successfully using a cloud model
        - The output quality is high (passed review/feedback)
        
        Args:
            prompt: The input prompt that was given to the model
            response: The model's response/output (code, text, etc.)
            domain: The domain (legal, accounting, data_analysis)
            task_type: The type of task (visualization, document, spreadsheet)
            rating: Quality rating 1-5 (5 = perfect, use for training)
            metadata: Additional metadata about the task
            model_used: The model that generated this output
            
        Returns:
            The ID of the captured example
        """
        example_id = str(uuid.uuid4())
        
        # Build the example record
        example = {
            "id": example_id,
            "prompt": prompt,
            "response": response,
            "domain": domain,
            "task_type": task_type,
            "rating": rating,
            "model_used": model_used,
            "metadata": metadata or {},
            "captured_at": datetime.utcnow().isoformat(),
            "curated": rating >= MIN_CURATION_RATING
        }
        
        # Write to teacher examples file
        self._append_to_jsonl(self.teacher_file, example)
        
        # If rating is high enough, also add to curated dataset
        if rating >= MIN_CURATION_RATING:
            self._append_to_jsonl(self.curated_file, example)
        
        return example_id
    
    def capture_task_completion(
        self,
        task_result: Dict[str, Any],
        task_request: Dict[str, Any],
        model_used: str = "gpt-4o"
    ) -> Optional[str]:
        """
        Capture a task completion result for distillation.
        
        This is a convenience method that extracts relevant information
        from a task result dictionary.
        
        Args:
            task_result: The result dictionary from task execution
                         Should contain: success, output/content, etc.
            task_request: The original task request
                          Should contain: user_request, domain, task_type
            model_used: The model that was used for this task
            
        Returns:
            The ID of the captured example, or None if not captured
        """
        # Only capture successful completions
        if not task_result.get("success", False):
            return None
        
        # Determine rating based on task success and review feedback
        rating = 5  # Default high rating for successful tasks
        
        # Downgrade if there was review feedback
        if task_result.get("review_feedback"):
            rating = 4
        
        # Further downgrade if there were issues
        if task_result.get("review_issues"):
            rating = 3
        
        # Extract prompt and response
        prompt = task_request.get("user_request", "")
        
        # For code generation tasks, the response is the generated code
        response = task_result.get("code", "")
        if not response:
            # Fall back to output/content
            response = task_result.get("output", "") or task_result.get("content", "")
        
        # Skip if no meaningful response
        if not response or len(response) < 50:
            return None
        
        # Build metadata
        metadata = {
            "retry_count": task_result.get("retry_count", 0),
            "review_attempts": task_result.get("review_attempts", 0),
            "execution_time": task_result.get("execution_time", 0),
            "chart_type": task_result.get("chart_type"),
            "output_format": task_result.get("output_format")
        }
        
        return self.capture_success(
            prompt=prompt,
            response=response,
            domain=task_request.get("domain", "data_analysis"),
            task_type=task_request.get("task_type", "visualization"),
            rating=rating,
            metadata=metadata,
            model_used=model_used
        )
    
    def _append_to_jsonl(self, filepath: str, record: Dict[str, Any]) -> None:
        """
        Append a record to a JSONL file.
        
        Args:
            filepath: Path to the JSONL file
            record: The record to append
        """
        with open(filepath, 'a') as f:
            f.write(json.dumps(record) + '\n')
    
    def get_dataset_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the collected dataset.
        
        Returns:
            Dictionary with dataset statistics
        """
        # Count examples in each file
        teacher_count = self._count_jsonl_lines(self.teacher_file)
        curated_count = self._count_jsonl_lines(self.curated_file)
        
        # Get domain distribution
        domain_dist = self._get_domain_distribution(self.curated_file)
        
        return {
            "teacher_examples": teacher_count,
            "curated_examples": curated_count,
            "min_for_training": MIN_EXAMPLES_FOR_TRAINING,
            "ready_for_training": curated_count >= MIN_EXAMPLES_FOR_TRAINING,
            "domain_distribution": domain_dist,
            "min_curation_rating": MIN_CURATION_RATING
        }
    
    def _count_jsonl_lines(self, filepath: str) -> int:
        """Count lines in a JSONL file."""
        try:
            with open(filepath, 'r') as f:
                return sum(1 for line in f if line.strip())
        except FileNotFoundError:
            return 0
    
    def _get_domain_distribution(self, filepath: str) -> Dict[str, int]:
        """Get distribution of examples by domain."""
        domain_counts = {}
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            record = json.loads(line)
                            domain = record.get("domain", "unknown")
                            domain_counts[domain] = domain_counts.get(domain, 0) + 1
                        except json.JSONDecodeError:
                            continue
        except FileNotFoundError:
            pass
        return domain_counts
    
    def get_curated_examples(
        self,
        domain: Optional[str] = None,
        min_rating: int = MIN_CURATION_RATING,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get curated examples from the dataset.
        
        Args:
            domain: Optional domain filter
            min_rating: Minimum rating to include
            limit: Maximum number of examples to return
            
        Returns:
            List of curated examples
        """
        examples = []
        
        try:
            with open(self.curated_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            record = json.loads(line)
                            
                            # Apply filters
                            if domain and record.get("domain") != domain:
                                continue
                            if record.get("rating", 0) < min_rating:
                                continue
                            
                            examples.append(record)
                            
                            if limit and len(examples) >= limit:
                                break
                        except json.JSONDecodeError:
                            continue
        except FileNotFoundError:
            pass
        
        return examples
    
    def export_for_training(
        self,
        output_path: Optional[str] = None,
        format: str = "alpaca"
    ) -> str:
        """
        Export the curated dataset in a specific format for training.
        
        Args:
            output_path: Path for the exported file
            format: Export format (alpaca, sharegpt, or raw)
            
        Returns:
            Path to the exported file
        """
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(self.output_dir, f"training_data_{timestamp}.json")
        
        examples = self.get_curated_examples()
        
        if format == "alpaca":
            # Alpaca format for fine-tuning
            training_data = [
                {
                    "instruction": ex["prompt"],
                    "output": ex["response"],
                    "input": ""
                }
                for ex in examples
            ]
        elif format == "sharegpt":
            # ShareGPT format for conversation fine-tuning
            training_data = [
                {
                    "conversations": [
                        {"from": "human", "value": ex["prompt"]},
                        {"from": "gpt", "value": ex["response"]}
                    ]
                }
                for ex in examples
            ]
        else:
            # Raw format
            training_data = examples
        
        with open(output_path, 'w') as f:
            json.dump(training_data, f, indent=2)
        
        return output_path


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def capture_cloud_success(
    prompt: str,
    response: str,
    domain: str,
    task_type: str,
    **kwargs
) -> str:
    """
    Convenience function to capture a successful cloud model output.
    
    Args:
        prompt: The input prompt
        response: The model's response
        domain: The task domain
        task_type: The task type
        **kwargs: Additional arguments for DistillationDataCollector.capture_success
        
    Returns:
        The ID of the captured example
    """
    collector = DistillationDataCollector()
    return collector.capture_success(
        prompt=prompt,
        response=response,
        domain=domain,
        task_type=task_type,
        model_used="gpt-4o",
        **kwargs
    )


def get_distillation_status() -> Dict[str, Any]:
    """
    Get the current status of the distillation dataset.
    
    Returns:
        Dictionary with dataset statistics
    """
    collector = DistillationDataCollector()
    return collector.get_dataset_stats()


if __name__ == "__main__":
    # Example usage
    print("Distillation Data Collector")
    print("=" * 50)
    
    # Initialize collector
    collector = DistillationDataCollector()
    
    # Get stats
    stats = collector.get_dataset_stats()
    print(f"Teacher examples: {stats['teacher_examples']}")
    print(f"Curated examples: {stats['curated_examples']}")
    print(f"Ready for training: {stats['ready_for_training']}")
    print(f"Domain distribution: {stats['domain_distribution']}")
    
    # Example: Capture a successful task
    print("\nExample: Capturing a successful task...")
    example_id = collector.capture_success(
        prompt="Create a bar chart showing sales by region",
        response="import pandas as pd\nimport matplotlib.pyplot as plt\n...",
        domain="data_analysis",
        task_type="visualization",
        rating=5,
        metadata={"chart_type": "bar", "columns": ["region", "sales"]}
    )
    print(f"Captured example ID: {example_id}")
