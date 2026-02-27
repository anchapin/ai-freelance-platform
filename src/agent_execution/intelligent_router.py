"""
Intelligent Task Categorization and Auto-Routing System

This module provides ML-based task classification and automatic routing
to optimize task distribution and improve success rates. It uses machine
learning models to categorize tasks and route them to the most appropriate
execution handlers based on historical performance data.

Features:
- ML-based task classification using embeddings and clustering
- Automatic routing based on task complexity and domain expertise
- Performance-based model selection and load balancing
- Historical data analysis for continuous improvement
- Integration with existing TaskRouter for seamless operation
"""

import os
import pickle
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

# Import existing components
from src.agent_execution.executor import (
    TaskRouter,
    TaskType,
    OutputFormat,
    LLMService,
)
from src.utils.logger import get_logger
from src.utils.telemetry import get_tracer

# Import database models
from src.api.models import Task, TaskStatus

# Import telemetry
from traceloop.sdk.decorators import task, workflow

# Initialize logger
logger = get_logger(__name__)

# Initialize telemetry
tracer = get_tracer(__name__)


@dataclass
class TaskProfile:
    """Represents a task's characteristics for ML analysis."""

    task_id: str
    domain: str
    user_request: str
    csv_headers: List[str]
    task_type: str
    output_format: str
    complexity_score: float
    estimated_time: float
    success_rate: float
    model_used: str
    retry_count: int
    review_attempts: int
    created_at: datetime
    execution_time: Optional[float] = None
    actual_success: Optional[bool] = None


@dataclass
class RouteDecision:
    """Represents a routing decision with confidence scores."""

    handler_type: str
    confidence: float
    reasoning: str
    estimated_performance: Dict[str, float]
    fallback_handlers: List[str]


class TaskClassifier:
    """
    ML-based task classifier using embeddings and clustering.

    Uses multiple classification approaches:
    1. Text-based classification using TF-IDF and Random Forest
    2. Clustering-based classification using K-means
    3. Rule-based classification for known patterns
    """

    def __init__(self, model_path: Optional[str] = None):
        """
        Initialize the task classifier.

        Args:
            model_path: Optional path to load pre-trained models
        """
        self.model_path = model_path or self._get_default_model_path()
        self.text_classifier = None
        self.clustering_model = None
        self.vectorizer = None
        self.label_encoder = None
        self.is_trained = False

        # Performance tracking
        self.classification_metrics = defaultdict(list)

        # Load existing models if available
        self._load_models()

    def _get_default_model_path(self) -> str:
        """Get default model storage path."""
        return os.path.join(os.path.dirname(__file__), "models", "task_classifier.pkl")

    def _load_models(self):
        """Load pre-trained models from disk."""
        try:
            if os.path.exists(self.model_path):
                with open(self.model_path, "rb") as f:
                    models = pickle.load(f)
                    self.text_classifier = models.get("classifier")
                    self.clustering_model = models.get("clustering")
                    self.vectorizer = models.get("vectorizer")
                    self.label_encoder = models.get("label_encoder")
                    self.is_trained = models.get("is_trained", False)
                logger.info("Loaded pre-trained task classification models")
            else:
                logger.info("No pre-trained models found, will train on first use")
        except Exception as e:
            logger.warning(f"Failed to load models: {e}")

    def _save_models(self):
        """Save trained models to disk."""
        try:
            os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
            models = {
                "classifier": self.text_classifier,
                "clustering": self.clustering_model,
                "vectorizer": self.vectorizer,
                "label_encoder": self.label_encoder,
                "is_trained": self.is_trained,
            }
            with open(self.model_path, "wb") as f:
                pickle.dump(models, f)
            logger.info("Saved task classification models")
        except Exception as e:
            logger.error(f"Failed to save models: {e}")

    def extract_features(self, task_profiles: List[TaskProfile]) -> np.ndarray:
        """
        Extract features from task profiles for ML classification.

        Features include:
        - Text features (TF-IDF of user request and domain)
        - Numerical features (complexity, estimated time, success rate)
        - Categorical features (domain, task type, output format)

        Args:
            task_profiles: List of task profiles

        Returns:
            Feature matrix
        """
        # Text features
        text_data = []
        for profile in task_profiles:
            text_features = f"{profile.domain} {profile.user_request} {' '.join(profile.csv_headers)}"
            text_data.append(text_features)

        # Vectorize text
        if self.vectorizer is None:
            self.vectorizer = TfidfVectorizer(
                max_features=1000,
                stop_words="english",
                ngram_range=(1, 2),
                min_df=2,
                max_df=0.8,
            )
            text_features = self.vectorizer.fit_transform(text_data)
        else:
            text_features = self.vectorizer.transform(text_data)

        # Numerical features
        numerical_features = []
        for profile in task_profiles:
            numerical_features.append(
                [
                    profile.complexity_score,
                    profile.estimated_time,
                    profile.success_rate,
                    profile.retry_count,
                    profile.review_attempts,
                ]
            )

        numerical_features = np.array(numerical_features)

        # Combine features
        if text_features.shape[0] > 0:
            combined_features = np.hstack([text_features.toarray(), numerical_features])
        else:
            combined_features = numerical_features

        return combined_features

    def train(self, task_profiles: List[TaskProfile], labels: List[str]):
        """
        Train the task classifier using historical data.

        Args:
            task_profiles: List of task profiles with features
            labels: Corresponding labels (handler types)
        """
        logger.info(f"Training task classifier with {len(task_profiles)} samples")

        # Extract features
        features = self.extract_features(task_profiles)

        # Train text classifier
        self.text_classifier = RandomForestClassifier(
            n_estimators=100, max_depth=10, random_state=42, class_weight="balanced"
        )

        self.text_classifier.fit(features, labels)

        # Train clustering model for anomaly detection
        self.clustering_model = KMeans(
            n_clusters=min(5, len(set(labels))), random_state=42
        )
        self.clustering_model.fit(features)

        self.is_trained = True
        self._save_models()

        # Log training metrics
        predictions = self.text_classifier.predict(features)
        accuracy = accuracy_score(labels, predictions)
        logger.info(f"Training accuracy: {accuracy:.3f}")

        # Store metrics
        self.classification_metrics["training_accuracy"].append(accuracy)

    def classify(self, task_profile: TaskProfile) -> Dict[str, Any]:
        """
        Classify a task and return routing recommendations.

        Args:
            task_profile: Task profile to classify

        Returns:
            Dictionary with classification results
        """
        if not self.is_trained:
            return self._rule_based_classification(task_profile)

        try:
            # Extract features
            features = self.extract_features([task_profile])

            # Get predictions
            probabilities = self.text_classifier.predict_proba(features)[0]
            predicted_class = self.text_classifier.predict(features)[0]

            # Get clustering information for anomaly detection
            cluster = self.clustering_model.predict(features)[0]

            # Calculate confidence
            confidence = max(probabilities)

            # Get top 3 predictions
            top_indices = np.argsort(probabilities)[-3:][::-1]
            top_predictions = [
                {
                    "handler": self.text_classifier.classes_[i],
                    "probability": probabilities[i],
                }
                for i in top_indices
            ]

            return {
                "predicted_handler": predicted_class,
                "confidence": confidence,
                "top_predictions": top_predictions,
                "cluster": int(cluster),
                "anomaly_score": self._calculate_anomaly_score(features, cluster),
                "method": "ml_classification",
            }

        except Exception as e:
            logger.warning(f"ML classification failed: {e}, falling back to rule-based")
            return self._rule_based_classification(task_profile)

    def _rule_based_classification(self, task_profile: TaskProfile) -> Dict[str, Any]:
        """
        Fallback rule-based classification for untrained models.

        Args:
            task_profile: Task profile to classify

        Returns:
            Dictionary with classification results
        """
        # Domain-based rules
        domain_rules = {
            "legal": ["legal_specialist", "document_generator"],
            "accounting": ["accounting_specialist", "spreadsheet_generator"],
            "data_analysis": ["visualization_specialist", "report_generator"],
        }

        # Complexity-based rules
        complexity_rules = {
            "high": ["expert_handler", "cloud_model"],
            "medium": ["standard_handler", "local_model"],
            "low": ["basic_handler", "template_based"],
        }

        # Output format rules
        format_rules = {
            "docx": ["document_generator", "legal_specialist"],
            "xlsx": ["spreadsheet_generator", "accounting_specialist"],
            "pdf": ["document_generator", "report_generator"],
            "image": ["visualization_specialist", "standard_handler"],
        }

        # Determine candidates
        candidates = []

        # Add domain-based candidates
        if task_profile.domain in domain_rules:
            candidates.extend(domain_rules[task_profile.domain])

        # Add complexity-based candidates
        if task_profile.complexity_score > 0.7:
            candidates.extend(complexity_rules["high"])
        elif task_profile.complexity_score > 0.4:
            candidates.extend(complexity_rules["medium"])
        else:
            candidates.extend(complexity_rules["low"])

        # Add format-based candidates
        if task_profile.output_format in format_rules:
            candidates.extend(format_rules[task_profile.output_format])

        # Count and rank candidates
        candidate_counts = Counter(candidates)
        top_candidates = candidate_counts.most_common(3)

        return {
            "predicted_handler": top_candidates[0][0]
            if top_candidates
            else "standard_handler",
            "confidence": 0.5,  # Lower confidence for rule-based
            "top_predictions": [
                {"handler": handler, "probability": count / len(candidates)}
                for handler, count in top_candidates
            ],
            "cluster": -1,
            "anomaly_score": 0.0,
            "method": "rule_based",
        }

    def _calculate_anomaly_score(self, features: np.ndarray, cluster: int) -> float:
        """
        Calculate anomaly score for a task profile.

        Args:
            features: Feature vector
            cluster: Assigned cluster

        Returns:
            Anomaly score (0.0 to 1.0)
        """
        try:
            # Calculate distance to cluster center
            center = self.clustering_model.cluster_centers_[cluster]
            distance = np.linalg.norm(features[0] - center)

            # Normalize by max distance in training data
            max_distance = np.max(
                [
                    np.linalg.norm(features[0] - c)
                    for c in self.clustering_model.cluster_centers_
                ]
            )

            return min(distance / max_distance if max_distance > 0 else 0.0, 1.0)
        except Exception:
            return 0.0


class PerformanceTracker:
    """
    Tracks and analyzes task execution performance for continuous improvement.
    """

    def __init__(self, db_session=None):
        """
        Initialize performance tracker.

        Args:
            db_session: Database session for storing performance data
        """
        self.db_session = db_session
        self.performance_data = defaultdict(list)
        self.handler_performance = defaultdict(lambda: defaultdict(list))

        # Performance metrics
        self.metrics = {
            "success_rate": defaultdict(float),
            "avg_execution_time": defaultdict(float),
            "avg_complexity": defaultdict(float),
            "task_volume": defaultdict(int),
        }

    def record_execution(self, task_profile: TaskProfile, actual_success: bool):
        """
        Record task execution results for performance analysis.

        Args:
            task_profile: Task profile
            actual_success: Whether the task was actually successful
        """
        handler = task_profile.model_used

        # Update performance data
        self.performance_data[handler].append(
            {
                "task_id": task_profile.task_id,
                "success": actual_success,
                "execution_time": task_profile.execution_time,
                "complexity": task_profile.complexity_score,
                "retry_count": task_profile.retry_count,
                "review_attempts": task_profile.review_attempts,
                "timestamp": datetime.now(),
            }
        )

        # Update handler performance metrics
        self.handler_performance[handler]["successes"].append(actual_success)
        if task_profile.execution_time:
            self.handler_performance[handler]["execution_times"].append(
                task_profile.execution_time
            )
        self.handler_performance[handler]["complexities"].append(
            task_profile.complexity_score
        )

        # Recalculate metrics
        self._update_metrics(handler)

    def _update_metrics(self, handler: str):
        """Update performance metrics for a handler."""
        data = self.handler_performance[handler]

        if data["successes"]:
            self.metrics["success_rate"][handler] = sum(data["successes"]) / len(
                data["successes"]
            )

        if data["execution_times"]:
            self.metrics["avg_execution_time"][handler] = np.mean(
                data["execution_times"]
            )

        if data["complexities"]:
            self.metrics["avg_complexity"][handler] = np.mean(data["complexities"])

        self.metrics["task_volume"][handler] = len(data["successes"])

    def get_handler_recommendations(
        self, task_profile: TaskProfile
    ) -> List[Dict[str, Any]]:
        """
        Get handler recommendations based on performance data.

        Args:
            task_profile: Task profile to get recommendations for

        Returns:
            List of handler recommendations with scores
        """
        recommendations = []

        # Get all unique handlers from metrics
        all_handlers = set(self.metrics["success_rate"].keys()) | set(
            self.metrics["avg_execution_time"].keys()
        )

        for handler in all_handlers:
            # Calculate composite score
            success_rate = self.metrics["success_rate"].get(handler, 0.0)
            avg_time = self.metrics["avg_execution_time"].get(handler, 0.0)
            avg_complexity = self.metrics["avg_complexity"].get(handler, 0.0)
            volume = self.metrics["task_volume"].get(handler, 0)

            # Composite score formula
            # Higher success rate = better
            # Lower execution time = better
            # Higher complexity handling = better for complex tasks
            # Higher volume = more proven

            time_score = max(
                0, 1 - (avg_time / 600)
            )  # Normalize to 0-1 (10 minutes max)
            complexity_score = min(1, avg_complexity / 1.0)  # Normalize to 0-1
            volume_score = min(1, volume / 100)  # Normalize to 0-1 (100 tasks max)

            # Weighted composite score
            composite_score = (
                success_rate * 0.4
                + time_score * 0.2
                + complexity_score * 0.2
                + volume_score * 0.2
            )

            recommendations.append(
                {
                    "handler": handler,
                    "score": composite_score,
                    "success_rate": success_rate,
                    "avg_execution_time": avg_time,
                    "avg_complexity": avg_complexity,
                    "task_volume": volume,
                }
            )

        # Sort by score
        recommendations.sort(key=lambda x: x["score"], reverse=True)
        return recommendations

    def get_complexity_thresholds(self) -> Dict[str, float]:
        """
        Calculate complexity thresholds for different handler types.

        Returns:
            Dictionary mapping handler types to complexity thresholds
        """
        thresholds = {}

        for handler, data in self.handler_performance.items():
            if data["complexities"]:
                complexities = data["complexities"]
                # Calculate percentiles
                p25 = np.percentile(complexities, 25)
                p50 = np.percentile(complexities, 50)
                p75 = np.percentile(complexities, 75)

                thresholds[handler] = {
                    "low": p25,
                    "medium": p50,
                    "high": p75,
                    "avg": np.mean(complexities),
                }

        return thresholds


class IntelligentRouter:
    """
    Intelligent task router that uses ML classification and performance data
    to make optimal routing decisions.
    """

    def __init__(self, db_session=None, model_path: Optional[str] = None):
        """
        Initialize the intelligent router.

        Args:
            db_session: Database session for performance tracking
            model_path: Optional path to load pre-trained models
        """
        self.classifier = TaskClassifier(model_path)
        self.performance_tracker = PerformanceTracker(db_session)
        self.task_router = TaskRouter()

        # Routing configuration
        self.confidence_threshold = 0.7
        self.anomaly_threshold = 0.8
        self.performance_weight = 0.6
        self.ml_weight = 0.4

        # Handler capabilities
        self.handler_capabilities = {
            "legal_specialist": {
                "domains": ["legal"],
                "formats": ["docx", "pdf"],
                "complexity": ["high", "medium"],
                "models": ["gpt-4o", "claude-opus"],
            },
            "accounting_specialist": {
                "domains": ["accounting"],
                "formats": ["xlsx", "pdf"],
                "complexity": ["high", "medium"],
                "models": ["gpt-4o", "claude-opus"],
            },
            "visualization_specialist": {
                "domains": ["data_analysis"],
                "formats": ["image"],
                "complexity": ["medium", "low"],
                "models": ["gpt-4o", "llama-3.2"],
            },
            "document_generator": {
                "domains": ["legal", "accounting", "data_analysis"],
                "formats": ["docx", "pdf"],
                "complexity": ["medium", "low"],
                "models": ["gpt-4o", "llama-3.2"],
            },
            "spreadsheet_generator": {
                "domains": ["accounting", "data_analysis"],
                "formats": ["xlsx"],
                "complexity": ["medium", "low"],
                "models": ["gpt-4o", "llama-3.2"],
            },
            "report_generator": {
                "domains": ["data_analysis"],
                "formats": ["docx", "pdf"],
                "complexity": ["medium", "low"],
                "models": ["gpt-4o", "llama-3.2"],
            },
            "standard_handler": {
                "domains": ["data_analysis"],
                "formats": ["image"],
                "complexity": ["low"],
                "models": ["llama-3.2"],
            },
        }

    @workflow(name="intelligent_routing")
    async def route_task(
        self,
        domain: str,
        user_request: str,
        csv_data: str,
        task_type: Optional[str] = None,
        output_format: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Route a task using intelligent classification and performance data.

        Args:
            domain: Task domain
            user_request: User's request
            csv_data: CSV data
            task_type: Optional task type
            output_format: Optional output format
            **kwargs: Additional routing parameters

        Returns:
            Dictionary with routing decision and execution results
        """
        # Create task profile
        task_profile = self._create_task_profile(
            domain, user_request, csv_data, task_type, output_format
        )

        # Classify task
        classification = self.classifier.classify(task_profile)

        # Get performance-based recommendations
        performance_recommendations = (
            self.performance_tracker.get_handler_recommendations(task_profile)
        )

        # Make routing decision
        decision = self._make_routing_decision(
            task_profile, classification, performance_recommendations
        )

        # Execute task with selected handler
        result = await self._execute_with_handler(task_profile, decision, **kwargs)

        # Record performance
        self.performance_tracker.record_execution(
            task_profile, result.get("success", False)
        )

        return {
            "routing_decision": decision,
            "classification": classification,
            "performance_recommendations": performance_recommendations,
            "execution_result": result,
            "task_profile": asdict(task_profile),
        }

    def _create_task_profile(
        self,
        domain: str,
        user_request: str,
        csv_data: str,
        task_type: Optional[str],
        output_format: Optional[str],
    ) -> TaskProfile:
        """
        Create a task profile from task parameters.

        Args:
            domain: Task domain
            user_request: User's request
            csv_data: CSV data
            task_type: Optional task type
            output_format: Optional output format

        Returns:
            TaskProfile instance
        """
        # Extract CSV headers
        first_line = csv_data.strip().split("\n")[0]
        csv_headers = [h.strip() for h in first_line.split(",")]

        # Calculate complexity score
        complexity = self._calculate_complexity_score(user_request, csv_headers, domain)

        # Estimate execution time
        estimated_time = self._estimate_execution_time(complexity, output_format)

        # Calculate success rate based on historical data
        success_rate = self._calculate_success_rate(domain, task_type, output_format)

        return TaskProfile(
            task_id=f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            domain=domain,
            user_request=user_request,
            csv_headers=csv_headers,
            task_type=task_type or self.task_router.detect_task_type(user_request),
            output_format=output_format
            or self.task_router.detect_output_format(
                domain, task_type or "visualization"
            ),
            complexity_score=complexity,
            estimated_time=estimated_time,
            success_rate=success_rate,
            model_used="llama-3.2",  # Will be updated after routing
            retry_count=0,
            review_attempts=0,
            created_at=datetime.now(),
        )

    def _calculate_complexity_score(
        self, user_request: str, csv_headers: List[str], domain: str
    ) -> float:
        """
        Calculate task complexity score based on various factors.

        Args:
            user_request: User's request
            csv_headers: CSV column headers
            domain: Task domain

        Returns:
            Complexity score (0.0 to 1.0)
        """
        score = 0.0

        # Request complexity
        request_length = len(user_request.split())
        if request_length > 20:
            score += 0.3
        elif request_length > 10:
            score += 0.2
        else:
            score += 0.1

        # Domain complexity
        if domain.lower() in ["legal", "accounting"]:
            score += 0.4
        else:
            score += 0.2

        # Data complexity
        num_columns = len(csv_headers)
        if num_columns > 10:
            score += 0.3
        elif num_columns > 5:
            score += 0.2
        else:
            score += 0.1

        # Request specificity
        if any(
            word in user_request.lower()
            for word in ["analyze", "predict", "forecast", "optimize"]
        ):
            score += 0.2

        return min(score / 1.0, 1.0)  # Normalize to 0-1

    def _estimate_execution_time(self, complexity: float, output_format: str) -> float:
        """
        Estimate execution time based on complexity and output format.

        Args:
            complexity: Task complexity score
            output_format: Output format

        Returns:
            Estimated execution time in seconds
        """
        base_time = 60  # Base 1 minute

        # Complexity multiplier
        time_multiplier = 1 + (complexity * 2)  # Up to 3x for high complexity

        # Format multiplier
        format_multipliers = {"image": 1.0, "docx": 1.5, "xlsx": 1.5, "pdf": 1.2}

        format_multiplier = format_multipliers.get(output_format, 1.0)

        return base_time * time_multiplier * format_multiplier

    def _calculate_success_rate(
        self, domain: str, task_type: str, output_format: str
    ) -> float:
        """
        Calculate expected success rate based on historical performance.

        Args:
            domain: Task domain
            task_type: Task type
            output_format: Output format

        Returns:
            Expected success rate (0.0 to 1.0)
        """
        # Base success rates by domain
        domain_rates = {"legal": 0.85, "accounting": 0.90, "data_analysis": 0.95}

        base_rate = domain_rates.get(domain.lower(), 0.90)

        # Adjust based on task type
        if task_type == "document":
            base_rate -= 0.05
        elif task_type == "spreadsheet":
            base_rate -= 0.03

        # Adjust based on output format
        if output_format in ["docx", "xlsx"]:
            base_rate -= 0.02

        return max(0.0, min(1.0, base_rate))

    def _make_routing_decision(
        self,
        task_profile: TaskProfile,
        classification: Dict[str, Any],
        performance_recommendations: List[Dict[str, Any]],
    ) -> RouteDecision:
        """
        Make routing decision based on classification and performance data.

        Args:
            task_profile: Task profile
            classification: ML classification results
            performance_recommendations: Performance-based recommendations

        Returns:
            RouteDecision instance
        """
        # Get top ML prediction
        ml_prediction = classification.get("predicted_handler", "standard_handler")
        ml_confidence = classification.get("confidence", 0.5)

        # Get top performance recommendation
        performance_recommendations[0] if performance_recommendations else None

        # Check for anomalies
        anomaly_score = classification.get("anomaly_score", 0.0)
        is_anomaly = anomaly_score > self.anomaly_threshold

        # Calculate composite scores
        candidates = {}

        # Add ML prediction
        if ml_confidence > self.confidence_threshold:
            candidates[ml_prediction] = ml_confidence * self.ml_weight

        # Add performance recommendations
        for rec in performance_recommendations[:3]:  # Top 3
            handler = rec["handler"]
            score = rec["score"] * self.performance_weight
            candidates[handler] = candidates.get(handler, 0) + score

        # Select best candidate
        if candidates:
            best_handler = max(candidates, key=candidates.get)
            best_score = candidates[best_handler]
        else:
            best_handler = "standard_handler"
            best_score = 0.5

        # Generate reasoning
        reasoning = self._generate_reasoning(
            task_profile,
            classification,
            performance_recommendations,
            best_handler,
            is_anomaly,
        )

        # Determine fallback handlers
        fallback_handlers = [
            rec["handler"]
            for rec in performance_recommendations[:3]
            if rec["handler"] != best_handler
        ]

        # Add ML prediction as fallback if not already included
        if ml_prediction != best_handler and ml_prediction not in fallback_handlers:
            fallback_handlers.append(ml_prediction)

        return RouteDecision(
            handler_type=best_handler,
            confidence=best_score,
            reasoning=reasoning,
            estimated_performance={
                "success_rate": self._get_estimated_success_rate(
                    best_handler, task_profile
                ),
                "execution_time": self._get_estimated_time(best_handler, task_profile),
                "complexity_match": self._get_complexity_match(
                    best_handler, task_profile
                ),
            },
            fallback_handlers=fallback_handlers[:3],  # Limit to 3 fallbacks
        )

    def _generate_reasoning(
        self,
        task_profile: TaskProfile,
        classification: Dict[str, Any],
        performance_recommendations: List[Dict[str, Any]],
        selected_handler: str,
        is_anomaly: bool,
    ) -> str:
        """
        Generate human-readable reasoning for routing decision.

        Args:
            task_profile: Task profile
            classification: ML classification results
            performance_recommendations: Performance-based recommendations
            selected_handler: Selected handler
            is_anomaly: Whether task is an anomaly

        Returns:
            Reasoning string
        """
        reasoning_parts = []

        # ML classification reasoning
        if classification.get("method") == "ml_classification":
            reasoning_parts.append(
                f"ML classification predicted '{classification['predicted_handler']}' "
                f"with {classification['confidence']:.2%} confidence"
            )
        else:
            reasoning_parts.append(
                "Used rule-based classification due to untrained model"
            )

        # Performance reasoning
        perf_rec = next(
            (
                r
                for r in performance_recommendations
                if r["handler"] == selected_handler
            ),
            None,
        )
        if perf_rec:
            reasoning_parts.append(
                f"Performance data shows {selected_handler} has {perf_rec['success_rate']:.1%} "
                f"success rate and handles {perf_rec['task_volume']} tasks"
            )

        # Anomaly detection
        if is_anomaly:
            reasoning_parts.append(
                "Task detected as anomaly, using conservative routing"
            )

        # Capability matching
        capabilities = self.handler_capabilities.get(selected_handler, {})
        if capabilities:
            reasoning_parts.append(
                f"Handler capabilities: domains={capabilities['domains']}, "
                f"formats={capabilities['formats']}, complexity={capabilities['complexity']}"
            )

        return " | ".join(reasoning_parts)

    def _get_estimated_success_rate(
        self, handler: str, task_profile: TaskProfile
    ) -> float:
        """Get estimated success rate for a handler and task."""
        perf_data = self.performance_tracker.metrics["success_rate"].get(handler, 0.8)
        complexity_penalty = max(0, 1 - task_profile.complexity_score)
        return perf_data * 0.7 + complexity_penalty * 0.3

    def _get_estimated_time(self, handler: str, task_profile: TaskProfile) -> float:
        """Get estimated execution time for a handler and task."""
        base_time = self.performance_tracker.metrics["avg_execution_time"].get(
            handler, 120
        )
        complexity_multiplier = 1 + (task_profile.complexity_score * 2)
        return base_time * complexity_multiplier

    def _get_complexity_match(self, handler: str, task_profile: TaskProfile) -> float:
        """Get complexity match score for a handler and task."""
        thresholds = self.performance_tracker.get_complexity_thresholds()
        handler_thresholds = thresholds.get(handler, {})

        if not handler_thresholds:
            return 0.5

        avg_complexity = handler_thresholds.get("avg", 0.5)
        task_complexity = task_profile.complexity_score

        # Calculate match score (closer to average is better)
        return 1 - abs(avg_complexity - task_complexity)

    async def _execute_with_handler(
        self, task_profile: TaskProfile, decision: RouteDecision, **kwargs
    ) -> Dict[str, Any]:
        """
        Execute task with the selected handler.

        Args:
            task_profile: Task profile
            decision: Routing decision
            **kwargs: Additional execution parameters

        Returns:
            Execution result
        """
        handler_type = decision.handler_type

        # Map handler types to execution methods
        handler_map = {
            "legal_specialist": self._execute_legal_task,
            "accounting_specialist": self._execute_accounting_task,
            "visualization_specialist": self._execute_visualization_task,
            "document_generator": self._execute_document_task,
            "spreadsheet_generator": self._execute_spreadsheet_task,
            "report_generator": self._execute_report_task,
            "standard_handler": self._execute_standard_task,
        }

        # Get execution method
        execution_method = handler_map.get(handler_type, self._execute_standard_task)

        try:
            # Execute task
            result = await execution_method(task_profile, **kwargs)

            # Update task profile with actual results
            task_profile.execution_time = result.get("execution_time", 0)
            task_profile.actual_success = result.get("success", False)
            task_profile.model_used = result.get("model_used", "unknown")

            return result

        except Exception as e:
            logger.error(f"Task execution failed for handler {handler_type}: {e}")

            # Try fallback handlers
            for fallback_handler in decision.fallback_handlers:
                try:
                    fallback_method = handler_map.get(
                        fallback_handler, self._execute_standard_task
                    )
                    result = await fallback_method(task_profile, **kwargs)

                    # Update task profile
                    task_profile.execution_time = result.get("execution_time", 0)
                    task_profile.actual_success = result.get("success", False)
                    task_profile.model_used = result.get("model_used", "unknown")

                    logger.info(
                        f"Task execution succeeded with fallback handler: {fallback_handler}"
                    )
                    return result

                except Exception as fallback_error:
                    logger.error(
                        f"Fallback execution failed for handler {fallback_handler}: {fallback_error}"
                    )
                    continue

            # All handlers failed
            return {
                "success": False,
                "message": f"All handlers failed. Last error: {str(e)}",
                "handler_type": handler_type,
                "execution_time": 0,
                "model_used": "none",
            }

    # Handler execution methods
    async def _execute_legal_task(
        self, task_profile: TaskProfile, **kwargs
    ) -> Dict[str, Any]:
        """Execute legal domain task."""
        # Use cloud model for legal tasks
        llm_service = LLMService.for_complex_task()

        # Execute with document generator for legal tasks
        result = await self._execute_document_task(
            task_profile, llm_service=llm_service, **kwargs
        )
        result["model_used"] = "gpt-4o"
        return result

    async def _execute_accounting_task(
        self, task_profile: TaskProfile, **kwargs
    ) -> Dict[str, Any]:
        """Execute accounting domain task."""
        # Use cloud model for accounting tasks
        llm_service = LLMService.for_complex_task()

        # Route to appropriate handler based on output format
        if task_profile.output_format == "xlsx":
            result = await self._execute_spreadsheet_task(
                task_profile, llm_service=llm_service, **kwargs
            )
        else:
            result = await self._execute_document_task(
                task_profile, llm_service=llm_service, **kwargs
            )

        result["model_used"] = "gpt-4o"
        return result

    async def _execute_visualization_task(
        self, task_profile: TaskProfile, **kwargs
    ) -> Dict[str, Any]:
        """Execute data visualization task."""
        # Use local model for cost optimization
        llm_service = LLMService.for_basic_admin()

        from src.agent_execution.executor import execute_data_visualization

        result = execute_data_visualization(
            csv_data="\n".join([",".join(task_profile.csv_headers)] + ["sample,data"]),
            user_request=task_profile.user_request,
            llm_service=llm_service,
            domain=task_profile.domain,
            **kwargs,
        )

        result["model_used"] = "llama-3.2"
        return result

    async def _execute_document_task(
        self, task_profile: TaskProfile, **kwargs
    ) -> Dict[str, Any]:
        """Execute document generation task."""
        llm_service = kwargs.get("llm_service", LLMService())

        from src.agent_execution.executor import DocumentGenerator

        generator = DocumentGenerator(
            domain=task_profile.domain,
            llm_service=llm_service,
            output_format=task_profile.output_format,
        )

        result = generator.generate_document(
            user_request=task_profile.user_request,
            csv_data="\n".join([",".join(task_profile.csv_headers)] + ["sample,data"]),
            **kwargs,
        )

        result["model_used"] = llm_service.get_config().get("model", "unknown")
        return result

    async def _execute_spreadsheet_task(
        self, task_profile: TaskProfile, **kwargs
    ) -> Dict[str, Any]:
        """Execute spreadsheet generation task."""
        llm_service = kwargs.get("llm_service", LLMService())

        from src.agent_execution.executor import execute_task

        result = execute_task(
            domain=task_profile.domain,
            user_request=task_profile.user_request,
            csv_data="\n".join([",".join(task_profile.csv_headers)] + ["sample,data"]),
            task_type=TaskType.SPREADSHEET,
            output_format=OutputFormat.XLSX,
            llm_service=llm_service,
            **kwargs,
        )

        result["model_used"] = llm_service.get_config().get("model", "unknown")
        return result

    async def _execute_report_task(
        self, task_profile: TaskProfile, **kwargs
    ) -> Dict[str, Any]:
        """Execute report generation task."""
        llm_service = kwargs.get("llm_service", LLMService())

        from src.agent_execution.executor import ReportGenerator

        generator = ReportGenerator(
            domain=task_profile.domain, llm_service=llm_service, report_type="detailed"
        )

        result = generator.generate_report(
            user_request=task_profile.user_request,
            csv_data="\n".join([",".join(task_profile.csv_headers)] + ["sample,data"]),
            **kwargs,
        )

        result["model_used"] = llm_service.get_config().get("model", "unknown")
        return result

    async def _execute_standard_task(
        self, task_profile: TaskProfile, **kwargs
    ) -> Dict[str, Any]:
        """Execute standard task using default routing."""
        # Use the existing TaskRouter for standard tasks
        result = self.task_router.route(
            domain=task_profile.domain,
            user_request=task_profile.user_request,
            csv_data="\n".join([",".join(task_profile.csv_headers)] + ["sample,data"]),
            task_type=task_profile.task_type,
            output_format=task_profile.output_format,
            **kwargs,
        )

        result["model_used"] = "standard"
        return result

    def get_routing_analytics(self) -> Dict[str, Any]:
        """
        Get analytics on routing decisions and performance.

        Returns:
            Dictionary with routing analytics
        """
        # Get performance recommendations to analyze current state
        sample_profile = TaskProfile(
            task_id="sample",
            domain="data_analysis",
            user_request="Analyze sales data",
            csv_headers=["date", "sales", "region"],
            task_type="visualization",
            output_format="image",
            complexity_score=0.5,
            estimated_time=120,
            success_rate=0.9,
            model_used="llama-3.2",
            retry_count=0,
            review_attempts=0,
            created_at=datetime.now(),
        )

        performance_recommendations = (
            self.performance_tracker.get_handler_recommendations(sample_profile)
        )

        return {
            "total_tasks_routed": sum(
                self.performance_tracker.metrics["task_volume"].values()
            ),
            "average_success_rate": np.mean(
                list(self.performance_tracker.metrics["success_rate"].values())
            )
            if self.performance_tracker.metrics["success_rate"]
            else 0.0,
            "top_performing_handlers": performance_recommendations[:3],
            "handler_distribution": dict(
                self.performance_tracker.metrics["task_volume"]
            ),
            "classification_accuracy": np.mean(
                self.classifier.classification_metrics["training_accuracy"]
            )
            if self.classifier.classification_metrics["training_accuracy"]
            else 0.0,
            "anomaly_detection_rate": self._calculate_anomaly_rate(),
        }

    def _calculate_anomaly_rate(self) -> float:
        """Calculate the rate of anomaly detection."""
        # This would be implemented based on actual anomaly tracking
        # For now, return a placeholder
        return 0.05  # 5% anomaly rate

    def retrain_classifier(self, db_session=None) -> bool:
        """
        Retrain the classifier with new performance data.

        Args:
            db_session: Database session for fetching training data

        Returns:
            True if retraining succeeded, False otherwise
        """
        try:
            # Fetch training data from database or performance tracker
            training_data = self._get_training_data(db_session)

            if not training_data:
                logger.warning("No training data available for retraining")
                return False

            task_profiles, labels = zip(*training_data)

            # Retrain classifier
            self.classifier.train(task_profiles, labels)

            logger.info("Successfully retrained task classifier")
            return True

        except Exception as e:
            logger.error(f"Failed to retrain classifier: {e}")
            return False

    def _get_training_data(self, db_session) -> List[Tuple[TaskProfile, str]]:
        """
        Get training data from database or performance tracker.

        Args:
            db_session: Database session

        Returns:
            List of (TaskProfile, handler_label) tuples
        """
        training_data = []

        # This would fetch actual task execution data from the database
        # For now, return empty list
        if db_session:
            try:
                # Query completed tasks with their execution results
                tasks = (
                    db_session.query(Task)
                    .filter(Task.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED]))
                    .limit(100)
                    .all()
                )

                for task in tasks:
                    # Create task profile from task data
                    profile = TaskProfile(
                        task_id=task.id,
                        domain=task.domain,
                        user_request=task.description or "",
                        csv_headers=[],
                        task_type=task.result_type or "visualization",
                        output_format=task.result_type or "image",
                        complexity_score=0.5,  # Would calculate from task data
                        estimated_time=120,
                        success_rate=0.8,
                        model_used=task.result_type or "standard",
                        retry_count=task.retry_count or 0,
                        review_attempts=0,
                        created_at=task.created_at or datetime.now(),
                    )

                    # Determine handler label based on task characteristics
                    handler_label = self._determine_handler_label(task)
                    training_data.append((profile, handler_label))

            except Exception as e:
                logger.error(f"Failed to fetch training data: {e}")

        return training_data

    def _determine_handler_label(self, task: Task) -> str:
        """
        Determine the handler label for a completed task.

        Args:
            task: Task instance

        Returns:
            Handler label string
        """
        # Logic to determine which handler was actually used
        # This would depend on how handlers are tracked in the system
        if task.domain == "legal":
            return "legal_specialist"
        elif task.domain == "accounting":
            return "accounting_specialist"
        elif task.result_type == "docx":
            return "document_generator"
        elif task.result_type == "xlsx":
            return "spreadsheet_generator"
        else:
            return "standard_handler"


# Global intelligent router instance
_intelligent_router_instance = None


def get_intelligent_router(
    db_session=None, model_path: Optional[str] = None
) -> IntelligentRouter:
    """
    Get the global intelligent router instance.

    Args:
        db_session: Database session
        model_path: Optional model path

    Returns:
        IntelligentRouter instance
    """
    global _intelligent_router_instance
    if _intelligent_router_instance is None:
        _intelligent_router_instance = IntelligentRouter(db_session, model_path)
    return _intelligent_router_instance


# Convenience function for direct task routing
@task(name="intelligent_task_routing")
async def route_task_intelligently(
    domain: str,
    user_request: str,
    csv_data: str,
    task_type: Optional[str] = None,
    output_format: Optional[str] = None,
    db_session=None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Convenience function to route a task intelligently.

    Args:
        domain: Task domain
        user_request: User's request
        csv_data: CSV data
        task_type: Optional task type
        output_format: Optional output format
        db_session: Database session
        **kwargs: Additional routing parameters

    Returns:
        Dictionary with routing and execution results
    """
    router = get_intelligent_router(db_session)
    return await router.route_task(
        domain=domain,
        user_request=user_request,
        csv_data=csv_data,
        task_type=task_type,
        output_format=output_format,
        **kwargs,
    )
