"""
Model Registry and Versioning

Tracks fine-tuned models, their versions, performance metrics, and deployment status.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class ModelStatus(str, Enum):
    """Status of a fine-tuned model."""

    TRAINING = "TRAINING"
    READY = "READY"
    DEPLOYED = "DEPLOYED"
    ARCHIVED = "ARCHIVED"
    FAILED = "FAILED"


@dataclass
class FinetuneJobRecord:
    """Record of a fine-tuning job."""

    job_id: str
    model_name: str
    base_model: str
    dataset_size: int
    training_time_seconds: float
    cost: float
    accuracy: Optional[float]
    status: str
    started_at: str
    completed_at: Optional[str]
    notes: str
    metadata: Dict[str, Any]


class ModelRegistry:
    """
    Registry for fine-tuned models with versioning and history.

    Features:
    - Track fine-tuned model versions
    - Store model metadata and metrics
    - Manage deployment status
    - Support rollback to previous versions
    - Cost tracking per model
    """

    def __init__(self, registry_path: Optional[str] = None):
        """
        Initialize model registry.

        Args:
            registry_path: Path to registry file
        """
        if registry_path is None:
            data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "data",
                "fine_tuning",
            )
            os.makedirs(data_dir, exist_ok=True)
            registry_path = os.path.join(data_dir, "model_registry.json")

        self.registry_path = registry_path
        self.models: Dict[str, List[Dict[str, Any]]] = self._load_registry()

    def _load_registry(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load registry from file."""
        if os.path.exists(self.registry_path):
            try:
                with open(self.registry_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load registry: {e}")
                return {}
        return {}

    def _save_registry(self) -> None:
        """Save registry to file."""
        with open(self.registry_path, "w") as f:
            json.dump(self.models, f, indent=2)

    def register_model(
        self,
        model_name: str,
        base_model: str,
        job_id: str,
        dataset_size: int,
        accuracy: Optional[float] = None,
        cost: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Register a new fine-tuned model version.

        Args:
            model_name: Name of the model
            base_model: Base model used for fine-tuning
            job_id: Fine-tuning job ID
            dataset_size: Number of training examples
            accuracy: Model accuracy (optional)
            cost: Training cost
            metadata: Additional metadata

        Returns:
            Model record
        """
        if model_name not in self.models:
            self.models[model_name] = []

        version = len(self.models[model_name]) + 1

        record = {
            "version": version,
            "model_name": model_name,
            "base_model": base_model,
            "job_id": job_id,
            "dataset_size": dataset_size,
            "accuracy": accuracy,
            "cost": cost,
            "status": ModelStatus.READY.value,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "deployed_at": None,
            "metadata": metadata or {},
        }

        self.models[model_name].append(record)
        self._save_registry()

        logger.info(f"Registered {model_name} v{version}")
        return record

    def get_model_version(self, model_name: str, version: Optional[int] = None) -> Optional[Dict]:
        """
        Get a specific model version.

        Args:
            model_name: Model name
            version: Version number (None for latest)

        Returns:
            Model record or None
        """
        if model_name not in self.models or not self.models[model_name]:
            return None

        if version is None:
            return self.models[model_name][-1]

        for record in self.models[model_name]:
            if record["version"] == version:
                return record

        return None

    def list_model_versions(self, model_name: str) -> List[Dict[str, Any]]:
        """
        List all versions of a model.

        Args:
            model_name: Model name

        Returns:
            List of model versions
        """
        return self.models.get(model_name, [])

    def set_model_status(
        self, model_name: str, status: str, version: Optional[int] = None
    ) -> bool:
        """
        Update model status.

        Args:
            model_name: Model name
            status: New status (READY, DEPLOYED, ARCHIVED, FAILED)
            version: Version number (None for latest)

        Returns:
            True if successful
        """
        record = self.get_model_version(model_name, version)
        if not record:
            return False

        record["status"] = status
        if status == ModelStatus.DEPLOYED.value:
            record["deployed_at"] = datetime.now(timezone.utc).isoformat()

        self._save_registry()
        logger.info(f"Updated {model_name} v{record['version']} status to {status}")
        return True

    def rollback_model(self, model_name: str, target_version: int) -> bool:
        """
        Rollback to a previous model version.

        Args:
            model_name: Model name
            target_version: Target version to rollback to

        Returns:
            True if successful
        """
        target_record = self.get_model_version(model_name, target_version)
        if not target_record:
            logger.error(f"Model {model_name} v{target_version} not found")
            return False

        # Set current version to archived
        current = self.get_model_version(model_name)
        if current:
            current["status"] = ModelStatus.ARCHIVED.value

        # Set target version to deployed
        target_record["status"] = ModelStatus.DEPLOYED.value
        target_record["deployed_at"] = datetime.now(timezone.utc).isoformat()

        self._save_registry()
        logger.info(f"Rolled back {model_name} to v{target_version}")
        return True

    def get_deployment_status(self) -> Dict[str, Dict[str, Any]]:
        """
        Get current deployment status of all models.

        Returns:
            Dictionary of deployed models
        """
        deployed = {}

        for model_name, versions in self.models.items():
            current = versions[-1] if versions else None
            if current and current["status"] == ModelStatus.DEPLOYED.value:
                deployed[model_name] = {
                    "version": current["version"],
                    "base_model": current["base_model"],
                    "accuracy": current["accuracy"],
                    "deployed_at": current["deployed_at"],
                }

        return deployed

    def get_cost_summary(self, model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get cost summary for model(s).

        Args:
            model_name: Optional specific model

        Returns:
            Cost summary
        """
        if model_name:
            versions = self.models.get(model_name, [])
            total_cost = sum(v.get("cost", 0) for v in versions)
            return {
                "model": model_name,
                "versions": len(versions),
                "total_cost": total_cost,
            }
        else:
            # All models
            summary = {
                "models": {},
                "total_cost": 0.0,
            }

            for name, versions in self.models.items():
                cost = sum(v.get("cost", 0) for v in versions)
                summary["models"][name] = {"versions": len(versions), "cost": cost}
                summary["total_cost"] += cost

            return summary

    def export_registry(self, filepath: str) -> None:
        """
        Export registry to JSON file.

        Args:
            filepath: Path to export
        """
        with open(filepath, "w") as f:
            json.dump(self.models, f, indent=2)
        logger.info(f"Exported model registry to {filepath}")

    def get_registry_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the registry.

        Returns:
            Statistics dictionary
        """
        total_models = len(self.models)
        total_versions = sum(len(v) for v in self.models.values())
        deployed_models = sum(
            1 for versions in self.models.values()
            if versions and versions[-1]["status"] == ModelStatus.DEPLOYED.value
        )
        total_cost = sum(
            v.get("cost", 0)
            for versions in self.models.values()
            for v in versions
        )

        return {
            "total_models": total_models,
            "total_versions": total_versions,
            "deployed_models": deployed_models,
            "total_training_cost": total_cost,
        }
