"""
OpenAI Fine-Tuning Integration

Handles fine-tuning with OpenAI's API for gpt-3.5-turbo and gpt-4o-mini.
"""

import json
import os
from typing import Optional, Dict, Any
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)


class OpenAIFineTuner:
    """
    Fine-tunes models using OpenAI's API.

    Supports:
    - gpt-3.5-turbo
    - gpt-4o-mini

    Features:
    - Upload training files to OpenAI
    - Submit fine-tuning jobs
    - Monitor job status
    - Cancel jobs
    """

    SUPPORTED_MODELS = ["gpt-3.5-turbo", "gpt-4o-mini"]

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize OpenAI fine-tuner.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY environment variable not set")

        self.client = OpenAI(api_key=self.api_key)

    def upload_training_file(self, filepath: str) -> str:
        """
        Upload training file to OpenAI.

        Args:
            filepath: Path to JSONL training file

        Returns:
            File ID
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Training file not found: {filepath}")

        with open(filepath, "rb") as f:
            response = self.client.files.create(file=f, purpose="fine-tune")

        file_id = response.id
        logger.info(f"Uploaded training file: {file_id}")
        return file_id

    def create_fine_tuning_job(
        self,
        model: str,
        training_file_id: str,
        validation_file_id: Optional[str] = None,
        suffix: Optional[str] = None,
        learning_rate_multiplier: float = 1.0,
        n_epochs: int = 3,
    ) -> Dict[str, Any]:
        """
        Create a fine-tuning job.

        Args:
            model: Base model (gpt-3.5-turbo or gpt-4o-mini)
            training_file_id: File ID of training data
            validation_file_id: Optional file ID of validation data
            suffix: Optional suffix for fine-tuned model name
            learning_rate_multiplier: Learning rate multiplier
            n_epochs: Number of training epochs

        Returns:
            Job details
        """
        if model not in self.SUPPORTED_MODELS:
            raise ValueError(f"Unsupported model: {model}. Supported: {self.SUPPORTED_MODELS}")

        # Create fine-tuning job
        kwargs = {
            "model": model,
            "training_file": training_file_id,
            "learning_rate_multiplier": learning_rate_multiplier,
            "n_epochs": n_epochs,
        }

        if validation_file_id:
            kwargs["validation_file"] = validation_file_id

        if suffix:
            kwargs["suffix"] = suffix

        job = self.client.fine_tuning.jobs.create(**kwargs)

        logger.info(f"Created fine-tuning job: {job.id}")
        return {
            "job_id": job.id,
            "model": job.model,
            "status": job.status,
            "training_file": job.training_file,
            "validation_file": job.validation_file,
            "fine_tuned_model": job.fine_tuned_model,
            "created_at": job.created_at,
        }

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        """
        Get fine-tuning job status.

        Args:
            job_id: Fine-tuning job ID

        Returns:
            Job status details
        """
        job = self.client.fine_tuning.jobs.retrieve(job_id)

        return {
            "job_id": job.id,
            "model": job.model,
            "status": job.status,
            "fine_tuned_model": job.fine_tuned_model,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "trained_tokens": getattr(job, "trained_tokens", None),
            "training_file": job.training_file,
        }

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a fine-tuning job.

        Args:
            job_id: Fine-tuning job ID

        Returns:
            True if cancelled successfully
        """
        try:
            self.client.fine_tuning.jobs.cancel(job_id)
            logger.info(f"Cancelled fine-tuning job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return False

    def list_jobs(self, limit: int = 10) -> list:
        """
        List recent fine-tuning jobs.

        Args:
            limit: Maximum number of jobs to return

        Returns:
            List of job details
        """
        jobs = self.client.fine_tuning.jobs.list(limit=limit)
        return [
            {
                "job_id": job.id,
                "model": job.model,
                "status": job.status,
                "fine_tuned_model": job.fine_tuned_model,
                "created_at": job.created_at,
            }
            for job in jobs.data
        ]

    def estimate_cost(self, training_tokens: int, model: str) -> Dict[str, float]:
        """
        Estimate fine-tuning cost.

        OpenAI pricing (as of 2024):
        - gpt-3.5-turbo: $0.003 per 1K input tokens, $0.006 per 1K output tokens
        - gpt-4o-mini: $0.015 per 1K input tokens, $0.06 per 1K output tokens

        Args:
            training_tokens: Number of training tokens
            model: Model name

        Returns:
            Cost estimate dictionary
        """
        if model == "gpt-3.5-turbo":
            input_cost_per_1k = 0.003
            output_cost_per_1k = 0.006
        elif model == "gpt-4o-mini":
            input_cost_per_1k = 0.015
            output_cost_per_1k = 0.06
        else:
            raise ValueError(f"Unknown model: {model}")

        # Estimate: assume 80% input, 20% output for training
        input_tokens = int(training_tokens * 0.8)
        output_tokens = int(training_tokens * 0.2)

        input_cost = (input_tokens / 1000) * input_cost_per_1k
        output_cost = (output_tokens / 1000) * output_cost_per_1k
        total_cost = input_cost + output_cost

        return {
            "model": model,
            "training_tokens": training_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "input_cost": input_cost,
            "output_cost": output_cost,
            "total_cost": total_cost,
            "currency": "USD",
        }

    def delete_fine_tuned_model(self, model_id: str) -> bool:
        """
        Delete a fine-tuned model.

        Args:
            model_id: Fine-tuned model ID

        Returns:
            True if deleted successfully
        """
        try:
            self.client.models.delete(model_id)
            logger.info(f"Deleted fine-tuned model: {model_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete model {model_id}: {e}")
            return False
