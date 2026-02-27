"""
Tests for the Intelligent Task Categorization and Auto-Routing System.

Tests ML-based task classification, automatic routing, performance tracking,
and integration with existing TaskRouter components.
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch
from datetime import datetime

from src.agent_execution.intelligent_router import (
    TaskClassifier,
    PerformanceTracker,
    IntelligentRouter,
    TaskProfile,
    RouteDecision,
    get_intelligent_router,
    route_task_intelligently,
)
from src.agent_execution.executor import TaskRouter


class TestTaskClassifier:
    """Test the ML-based task classifier."""

    def test_task_profile_creation(self):
        """Test TaskProfile dataclass creation."""
        profile = TaskProfile(
            task_id="test-task-123",
            domain="data_analysis",
            user_request="Create a bar chart of sales data",
            csv_headers=["date", "sales", "region"],
            task_type="visualization",
            output_format="image",
            complexity_score=0.6,
            estimated_time=120.0,
            success_rate=0.85,
            model_used="llama-3.2",
            retry_count=0,
            review_attempts=0,
            created_at=datetime.now(),
        )

        assert profile.task_id == "test-task-123"
        assert profile.domain == "data_analysis"
        assert profile.user_request == "Create a bar chart of sales data"
        assert profile.csv_headers == ["date", "sales", "region"]
        assert profile.complexity_score == 0.6
        assert profile.estimated_time == 120.0

    def test_extract_features(self):
        """Test feature extraction from task profiles."""
        classifier = TaskClassifier()

        profiles = [
            TaskProfile(
                task_id="test-1",
                domain="data_analysis",
                user_request="Create a bar chart",
                csv_headers=["sales", "region"],
                task_type="visualization",
                output_format="image",
                complexity_score=0.5,
                estimated_time=120.0,
                success_rate=0.8,
                model_used="llama-3.2",
                retry_count=0,
                review_attempts=0,
                created_at=datetime.now(),
            ),
            TaskProfile(
                task_id="test-2",
                domain="legal",
                user_request="Generate a contract",
                csv_headers=["party_a", "party_b", "amount"],
                task_type="document",
                output_format="docx",
                complexity_score=0.8,
                estimated_time=300.0,
                success_rate=0.7,
                model_used="gpt-4o",
                retry_count=1,
                review_attempts=2,
                created_at=datetime.now(),
            ),
        ]

        features = classifier.extract_features(profiles)

        assert features.shape[0] == 2  # Two profiles
        assert features.shape[1] > 5  # At least 5 features (text + numerical)
        assert not np.isnan(features).any()  # No NaN values

    def test_rule_based_classification(self):
        """Test rule-based classification fallback."""
        classifier = TaskClassifier()

        profile = TaskProfile(
            task_id="test",
            domain="legal",
            user_request="Create a contract document",
            csv_headers=["party_a", "party_b"],
            task_type="document",
            output_format="docx",
            complexity_score=0.8,
            estimated_time=300.0,
            success_rate=0.7,
            model_used="gpt-4o",
            retry_count=0,
            review_attempts=0,
            created_at=datetime.now(),
        )

        result = classifier._rule_based_classification(profile)

        assert "predicted_handler" in result
        assert "confidence" in result
        assert "top_predictions" in result
        assert result["confidence"] == 0.5  # Rule-based has lower confidence
        assert result["method"] == "rule_based"

    def test_calculate_anomaly_score(self):
        """Test anomaly score calculation."""
        classifier = TaskClassifier()

        # Mock clustering model
        classifier.clustering_model = Mock()
        classifier.clustering_model.cluster_centers_ = np.array([[0.5, 0.5, 0.5]])

        features = np.array([[0.1, 0.1, 0.1]])  # Far from center
        cluster = 0

        score = classifier._calculate_anomaly_score(features, cluster)

        assert 0.0 <= score <= 1.0
        assert score > 0.5  # Should be anomalous

    @pytest.mark.asyncio
    async def test_train_classifier(self):
        """Test classifier training with sample data."""
        classifier = TaskClassifier()

        # Create sample training data
        profiles = []
        labels = []

        for i in range(20):
            profile = TaskProfile(
                task_id=f"task-{i}",
                domain="data_analysis" if i < 10 else "legal",
                user_request=f"Task {i}",
                csv_headers=["col1", "col2"],
                task_type="visualization" if i < 10 else "document",
                output_format="image" if i < 10 else "docx",
                complexity_score=0.5,
                estimated_time=120.0,
                success_rate=0.8,
                model_used="llama-3.2",
                retry_count=0,
                review_attempts=0,
                created_at=datetime.now(),
            )
            profiles.append(profile)
            labels.append("visualization_specialist" if i < 10 else "legal_specialist")

        # Train classifier
        classifier.train(profiles, labels)

        assert classifier.is_trained
        assert classifier.text_classifier is not None
        assert classifier.clustering_model is not None
        assert classifier.vectorizer is not None

    @pytest.mark.asyncio
    async def test_classify_task(self):
        """Test task classification."""
        classifier = TaskClassifier()

        # Create sample training data
        profiles = []
        labels = []

        for i in range(20):
            profile = TaskProfile(
                task_id=f"task-{i}",
                domain="data_analysis" if i < 10 else "legal",
                user_request=f"Task {i}",
                csv_headers=["col1", "col2"],
                task_type="visualization" if i < 10 else "document",
                output_format="image" if i < 10 else "docx",
                complexity_score=0.5,
                estimated_time=120.0,
                success_rate=0.8,
                model_used="llama-3.2",
                retry_count=0,
                review_attempts=0,
                created_at=datetime.now(),
            )
            profiles.append(profile)
            labels.append("visualization_specialist" if i < 10 else "legal_specialist")

        # Train classifier
        classifier.train(profiles, labels)

        # Test classification
        test_profile = TaskProfile(
            task_id="test",
            domain="data_analysis",
            user_request="Create a bar chart of sales data",
            csv_headers=["sales", "region"],
            task_type="visualization",
            output_format="image",
            complexity_score=0.5,
            estimated_time=120.0,
            success_rate=0.8,
            model_used="llama-3.2",
            retry_count=0,
            review_attempts=0,
            created_at=datetime.now(),
        )

        result = classifier.classify(test_profile)

        assert "predicted_handler" in result
        assert "confidence" in result
        assert "top_predictions" in result
        assert "cluster" in result
        assert "anomaly_score" in result
        assert "method" in result
        assert result["method"] == "ml_classification"


class TestPerformanceTracker:
    """Test the performance tracking system."""

    def test_record_execution(self):
        """Test recording task execution results."""
        tracker = PerformanceTracker()

        profile = TaskProfile(
            task_id="test-task",
            domain="data_analysis",
            user_request="Test request",
            csv_headers=["col1", "col2"],
            task_type="visualization",
            output_format="image",
            complexity_score=0.5,
            estimated_time=120.0,
            success_rate=0.8,
            model_used="llama-3.2",
            retry_count=0,
            review_attempts=0,
            created_at=datetime.now(),
            execution_time=150.0,
            actual_success=True,
        )

        tracker.record_execution(profile, True)

        # Check that data was recorded
        assert "llama-3.2" in tracker.performance_data
        assert len(tracker.performance_data["llama-3.2"]) == 1
        assert tracker.performance_data["llama-3.2"][0]["success"]
        assert tracker.performance_data["llama-3.2"][0]["execution_time"] == 150.0

    def test_get_handler_recommendations(self):
        """Test getting handler recommendations based on performance."""
        tracker = PerformanceTracker()

        # Record some sample data
        for i in range(10):
            profile = TaskProfile(
                task_id=f"task-{i}",
                domain="data_analysis",
                user_request=f"Task {i}",
                csv_headers=["col1", "col2"],
                task_type="visualization",
                output_format="image",
                complexity_score=0.5,
                estimated_time=120.0,
                success_rate=0.8,
                model_used="llama-3.2",
                retry_count=0,
                review_attempts=0,
                created_at=datetime.now(),
                execution_time=120.0 + i * 10,
                actual_success=(i % 2 == 0),  # 50% success rate
            )
            tracker.record_execution(profile, profile.actual_success)

        # Add data for another handler
        for i in range(5):
            profile = TaskProfile(
                task_id=f"gpt-task-{i}",
                domain="legal",
                user_request=f"Task {i}",
                csv_headers=["col1", "col2"],
                task_type="document",
                output_format="docx",
                complexity_score=0.8,
                estimated_time=300.0,
                success_rate=0.9,
                model_used="gpt-4o",
                retry_count=0,
                review_attempts=0,
                created_at=datetime.now(),
                execution_time=250.0 + i * 5,
                actual_success=True,  # 100% success rate
            )
            tracker.record_execution(profile, profile.actual_success)

        # Get recommendations
        sample_profile = TaskProfile(
            task_id="sample",
            domain="data_analysis",
            user_request="Sample request",
            csv_headers=["col1", "col2"],
            task_type="visualization",
            output_format="image",
            complexity_score=0.5,
            estimated_time=120.0,
            success_rate=0.8,
            model_used="llama-3.2",
            retry_count=0,
            review_attempts=0,
            created_at=datetime.now(),
        )

        recommendations = tracker.get_handler_recommendations(sample_profile)

        assert len(recommendations) > 0
        assert all("handler" in rec for rec in recommendations)
        assert all("score" in rec for rec in recommendations)

        # gpt-4o should have higher score due to better performance
        gpt_rec = next((r for r in recommendations if r["handler"] == "gpt-4o"), None)
        llama_rec = next(
            (r for r in recommendations if r["handler"] == "llama-3.2"), None
        )

        if gpt_rec and llama_rec:
            assert gpt_rec["score"] > llama_rec["score"]

    def test_get_complexity_thresholds(self):
        """Test getting complexity thresholds for handlers."""
        tracker = PerformanceTracker()

        # Record sample data with different complexities
        complexities = [0.3, 0.5, 0.7, 0.9, 0.4]

        for i, complexity in enumerate(complexities):
            profile = TaskProfile(
                task_id=f"task-{i}",
                domain="data_analysis",
                user_request=f"Task {i}",
                csv_headers=["col1", "col2"],
                task_type="visualization",
                output_format="image",
                complexity_score=complexity,
                estimated_time=120.0,
                success_rate=0.8,
                model_used="llama-3.2",
                retry_count=0,
                review_attempts=0,
                created_at=datetime.now(),
                execution_time=120.0,
                actual_success=True,
            )
            tracker.record_execution(profile, True)

        thresholds = tracker.get_complexity_thresholds()

        assert "llama-3.2" in thresholds
        assert "low" in thresholds["llama-3.2"]
        assert "medium" in thresholds["llama-3.2"]
        assert "high" in thresholds["llama-3.2"]
        assert "avg" in thresholds["llama-3.2"]


class TestIntelligentRouter:
    """Test the intelligent router system."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        return Mock()

    @pytest.fixture
    def intelligent_router(self, mock_db_session):
        """Create an intelligent router instance."""
        return IntelligentRouter(db_session=mock_db_session)

    def test_create_task_profile(self, intelligent_router):
        """Test creating a task profile from parameters."""
        profile = intelligent_router._create_task_profile(
            domain="data_analysis",
            user_request="Create a bar chart of sales data",
            csv_data="date,sales,region\n2023-01-01,100,North\n2023-01-02,150,South",
            task_type=None,
            output_format=None,
        )

        assert profile.domain == "data_analysis"
        assert profile.user_request == "Create a bar chart of sales data"
        assert profile.csv_headers == ["date", "sales", "region"]
        assert profile.task_type == "visualization"  # Should be detected
        assert profile.output_format == "image"  # Should be detected
        assert 0.0 <= profile.complexity_score <= 1.0
        assert profile.estimated_time > 0
        assert 0.0 <= profile.success_rate <= 1.0

    def test_calculate_complexity_score(self, intelligent_router):
        """Test complexity score calculation."""
        # Simple request
        score1 = intelligent_router._calculate_complexity_score(
            "Create a chart", ["col1", "col2"], "data_analysis"
        )

        # Complex request
        score2 = intelligent_router._calculate_complexity_score(
            "Analyze the complex relationships between multiple variables in the dataset and create a comprehensive visualization that shows trends, patterns, and correlations over time",
            [
                "date",
                "sales",
                "region",
                "product",
                "customer_type",
                "channel",
                "price",
                "cost",
                "profit",
            ],
            "data_analysis",
        )

        assert 0.0 <= score1 <= 1.0
        assert 0.0 <= score2 <= 1.0
        assert score2 > score1  # Complex request should have higher score

    def test_calculate_success_rate(self, intelligent_router):
        """Test success rate calculation."""
        # High success rate domain
        rate1 = intelligent_router._calculate_success_rate(
            "data_analysis", "visualization", "image"
        )

        # Lower success rate for complex formats
        rate2 = intelligent_router._calculate_success_rate("legal", "document", "docx")

        assert 0.0 <= rate1 <= 1.0
        assert 0.0 <= rate2 <= 1.0
        assert rate1 > rate2  # Data analysis should have higher base rate

    def test_make_routing_decision(self, intelligent_router):
        """Test making routing decisions."""
        profile = TaskProfile(
            task_id="test",
            domain="data_analysis",
            user_request="Create a bar chart",
            csv_headers=["sales", "region"],
            task_type="visualization",
            output_format="image",
            complexity_score=0.5,
            estimated_time=120.0,
            success_rate=0.8,
            model_used="llama-3.2",
            retry_count=0,
            review_attempts=0,
            created_at=datetime.now(),
        )

        classification = {
            "predicted_handler": "visualization_specialist",
            "confidence": 0.8,
            "top_predictions": [
                {"handler": "visualization_specialist", "probability": 0.8},
                {"handler": "standard_handler", "probability": 0.15},
            ],
            "cluster": 1,
            "anomaly_score": 0.1,
            "method": "ml_classification",
        }

        performance_recommendations = [
            {
                "handler": "visualization_specialist",
                "score": 0.9,
                "success_rate": 0.95,
                "avg_execution_time": 120.0,
                "avg_complexity": 0.6,
                "task_volume": 50,
            },
            {
                "handler": "standard_handler",
                "score": 0.7,
                "success_rate": 0.85,
                "avg_execution_time": 100.0,
                "avg_complexity": 0.4,
                "task_volume": 100,
            },
        ]

        decision = intelligent_router._make_routing_decision(
            profile, classification, performance_recommendations
        )

        assert isinstance(decision, RouteDecision)
        assert decision.handler_type == "visualization_specialist"
        assert decision.confidence > 0.0
        assert decision.reasoning  # Check reasoning is non-empty
        assert len(decision.fallback_handlers) > 0
        assert "success_rate" in decision.estimated_performance
        assert "execution_time" in decision.estimated_performance
        assert "complexity_match" in decision.estimated_performance

    @pytest.mark.asyncio
    async def test_route_task(self, intelligent_router):
        """Test end-to-end task routing."""
        result = await intelligent_router.route_task(
            domain="data_analysis",
            user_request="Create a bar chart of sales data",
            csv_data="date,sales,region\n2023-01-01,100,North\n2023-01-02,150,South",
            task_type=None,
            output_format=None,
        )

        assert "routing_decision" in result
        assert "classification" in result
        assert "performance_recommendations" in result
        assert "execution_result" in result
        assert "task_profile" in result

        # Check that task profile was created
        task_profile = result["task_profile"]
        assert task_profile["domain"] == "data_analysis"
        assert task_profile["user_request"] == "Create a bar chart of sales data"

        # Check that routing decision was made
        routing_decision = result["routing_decision"]
        assert isinstance(routing_decision, RouteDecision)

        # Check that execution was attempted
        execution_result = result["execution_result"]
        assert "success" in execution_result
        assert "model_used" in execution_result

    @pytest.mark.asyncio
    async def test_route_legal_task(self, intelligent_router):
        """Test routing a legal domain task."""
        result = await intelligent_router.route_task(
            domain="legal",
            user_request="Generate a contract document",
            csv_data="party_a,party_b,amount\nClient,Provider,10000",
            task_type="document",
            output_format="docx",
        )

        # Should route to legal specialist
        routing_decision = result["routing_decision"]
        assert routing_decision.handler_type in [
            "legal_specialist",
            "document_generator",
        ]

        # Should use cloud model
        execution_result = result["execution_result"]
        assert execution_result.get("model_used") in ["gpt-4o", "claude-opus"]

    @pytest.mark.asyncio
    async def test_route_accounting_task(self, intelligent_router):
        """Test routing an accounting domain task."""
        # Mock classification to return accounting specialist
        mock_classification = {
            "predicted_handler": "accounting_specialist",
            "confidence": 0.8,
            "top_predictions": [
                {"handler": "accounting_specialist", "probability": 0.8},
                {"handler": "spreadsheet_generator", "probability": 0.15},
            ],
            "cluster": 0,
            "anomaly_score": 0.1,
            "method": "rule_based",
        }

        # Mock performance recommendations to prefer accounting specialist
        mock_recommendations = [
            {
                "handler": "accounting_specialist",
                "score": 0.9,
                "success_rate": 0.95,
                "avg_execution_time": 120.0,
                "avg_complexity": 0.8,
                "task_volume": 50,
            }
        ]

        with (
            patch.object(
                intelligent_router.classifier,
                "classify",
                return_value=mock_classification,
            ),
            patch.object(
                intelligent_router.performance_tracker,
                "get_handler_recommendations",
                return_value=mock_recommendations,
            ),
        ):
            result = await intelligent_router.route_task(
                domain="accounting",
                user_request="Create a financial spreadsheet",
                csv_data="date,amount,category\n2023-01-01,1000,Revenue\n2023-01-02,500,Expense",
                task_type="spreadsheet",
                output_format="xlsx",
            )

            # Should route to accounting specialist
            routing_decision = result["routing_decision"]
            assert routing_decision.handler_type in [
                "accounting_specialist",
                "spreadsheet_generator",
            ]

            # Should use cloud model
            execution_result = result["execution_result"]
            assert execution_result.get("model_used") in ["gpt-4o", "claude-opus"]

    def test_get_routing_analytics(self, intelligent_router):
        """Test getting routing analytics."""
        analytics = intelligent_router.get_routing_analytics()

        assert "total_tasks_routed" in analytics
        assert "average_success_rate" in analytics
        assert "top_performing_handlers" in analytics
        assert "handler_distribution" in analytics
        assert "classification_accuracy" in analytics
        assert "anomaly_detection_rate" in analytics

        assert isinstance(analytics["total_tasks_routed"], (int, float))
        assert 0.0 <= analytics["average_success_rate"] <= 1.0
        assert isinstance(analytics["top_performing_handlers"], list)
        assert isinstance(analytics["handler_distribution"], dict)

    def test_retrain_classifier(self, intelligent_router, mock_db_session):
        """Test retraining the classifier."""
        # Mock database session and task data
        mock_task = Mock()
        mock_task.id = "task-123"
        mock_task.domain = "data_analysis"
        mock_task.description = "Test task"
        mock_task.result_type = "image"
        mock_task.retry_count = 0
        mock_task.created_at = datetime.now()

        mock_db_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [
            mock_task
        ]

        # Retrain classifier
        result = intelligent_router.retrain_classifier(mock_db_session)

        # Should return True if retraining succeeded
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_fallback_handling(self, intelligent_router):
        """Test fallback handling when primary handler fails."""

        # Mock a handler that fails
        async def failing_handler(task_profile, **kwargs):
            raise Exception("Handler failed")

        # Mock a handler that succeeds
        async def successful_handler(task_profile, **kwargs):
            return {
                "success": True,
                "message": "Task completed successfully",
                "execution_time": 120.0,
                "model_used": "llama-3.2",
            }

        # Create a routing decision with visualization_specialist in fallback handlers
        mock_decision = RouteDecision(
            handler_type="standard_handler",
            confidence=0.5,
            reasoning="Test routing decision",
            estimated_performance={
                "success_rate": 0.8,
                "execution_time": 120.0,
                "complexity_match": 0.5,
            },
            fallback_handlers=["visualization_specialist"],
        )

        # Patch the execution methods and routing decision
        with (
            patch.object(
                intelligent_router,
                "_execute_standard_task",
                side_effect=failing_handler,
            ),
            patch.object(
                intelligent_router,
                "_execute_visualization_task",
                side_effect=successful_handler,
            ),
            patch.object(
                intelligent_router,
                "_make_routing_decision",
                return_value=mock_decision,
            ),
        ):
            result = await intelligent_router.route_task(
                domain="data_analysis",
                user_request="Create a chart",
                csv_data="col1,col2\n1,2\n3,4",
                task_type="visualization",
                output_format="image",
            )

            # Should succeed with fallback
            execution_result = result["execution_result"]
            assert execution_result["success"]
            assert "Task completed successfully" in execution_result["message"]


class TestIntegration:
    """Integration tests for the intelligent router."""

    @pytest.mark.asyncio
    async def test_integration_with_task_router(self):
        """Test integration with existing TaskRouter."""

        # Create intelligent router
        router = IntelligentRouter()

        # Test that it can work with existing TaskRouter
        task_router = TaskRouter()

        # Both should be able to handle the same task
        csv_data = "date,sales,region\n2023-01-01,100,North\n2023-01-02,150,South"

        # Test TaskRouter
        result1 = task_router.route(
            domain="data_analysis", user_request="Create a bar chart", csv_data=csv_data
        )

        # Test IntelligentRouter
        result2 = await router.route_task(
            domain="data_analysis", user_request="Create a bar chart", csv_data=csv_data
        )

        # Both should succeed
        assert result1 is not None
        assert result2 is not None

        # Intelligent router should have additional metadata
        assert "routing_decision" in result2
        assert "classification" in result2
        assert "performance_recommendations" in result2

    @pytest.mark.asyncio
    async def test_convenience_function(self):
        """Test the convenience function for task routing."""
        # Mock database session
        mock_db_session = Mock()

        # Test convenience function
        result = await route_task_intelligently(
            domain="data_analysis",
            user_request="Create a visualization",
            csv_data="col1,col2\n1,2\n3,4",
            db_session=mock_db_session,
        )

        assert result is not None
        assert "routing_decision" in result
        assert "execution_result" in result

    def test_global_router_instance(self):
        """Test the global router instance."""
        # Get router instance
        router1 = get_intelligent_router()
        router2 = get_intelligent_router()

        # Should return the same instance
        assert router1 is router2

        # Should be an IntelligentRouter instance
        assert isinstance(router1, IntelligentRouter)

    @pytest.mark.asyncio
    async def test_performance_tracking_integration(self):
        """Test integration with performance tracking."""
        router = IntelligentRouter()

        # Route a task
        result = await router.route_task(
            domain="data_analysis",
            user_request="Create a chart",
            csv_data="col1,col2\n1,2\n3,4",
        )

        # Check that performance was tracked
        task_profile = result["task_profile"]
        handler = task_profile.get("model_used", "unknown")

        # Should have recorded execution data
        assert handler in router.performance_tracker.performance_data
        assert len(router.performance_tracker.performance_data[handler]) > 0


class TestErrorHandling:
    """Test error handling in the intelligent router."""

    @pytest.mark.asyncio
    async def test_classifier_failure_handling(self):
        """Test handling when classifier fails."""
        router = IntelligentRouter()

        # Mock classifier to fail
        router.classifier.classify = Mock(side_effect=Exception("Classifier failed"))

        # Should still work with fallback
        result = await router.route_task(
            domain="data_analysis",
            user_request="Create a chart",
            csv_data="col1,col2\n1,2\n3,4",
        )

        assert result is not None
        assert "routing_decision" in result
        assert "execution_result" in result

    @pytest.mark.asyncio
    async def test_performance_tracker_failure_handling(self):
        """Test handling when performance tracker fails."""
        router = IntelligentRouter()

        # Mock performance tracker to fail
        router.performance_tracker.get_handler_recommendations = Mock(
            side_effect=Exception("Performance tracker failed")
        )

        # Should still work with fallback
        result = await router.route_task(
            domain="data_analysis",
            user_request="Create a chart",
            csv_data="col1,col2\n1,2\n3,4",
        )

        assert result is not None
        assert "routing_decision" in result
        assert "execution_result" in result

    @pytest.mark.asyncio
    async def test_execution_failure_handling(self):
        """Test handling when task execution fails."""
        router = IntelligentRouter()

        # Mock all execution methods to fail
        async def failing_execution(*args, **kwargs):
            raise Exception("Execution failed")

        router._execute_standard_task = Mock(side_effect=failing_execution)
        router._execute_visualization_task = Mock(side_effect=failing_execution)
        router._execute_document_task = Mock(side_effect=failing_execution)

        # Should handle failure gracefully
        result = await router.route_task(
            domain="data_analysis",
            user_request="Create a chart",
            csv_data="col1,col2\n1,2\n3,4",
        )

        assert result is not None
        assert "routing_decision" in result
        assert "execution_result" in result

        # Execution should have failed
        execution_result = result["execution_result"]
        assert not execution_result["success"]
        assert "All handlers failed" in execution_result["message"]


# Helper functions for testing
def create_test_task_profile(
    domain: str = "data_analysis", complexity: float = 0.5
) -> TaskProfile:
    """Create a test task profile."""
    return TaskProfile(
        task_id="test-task",
        domain=domain,
        user_request="Test request",
        csv_headers=["col1", "col2"],
        task_type="visualization",
        output_format="image",
        complexity_score=complexity,
        estimated_time=120.0,
        success_rate=0.8,
        model_used="llama-3.2",
        retry_count=0,
        review_attempts=0,
        created_at=datetime.now(),
    )


def create_mock_task(domain: str = "data_analysis", status: str = "COMPLETED") -> Mock:
    """Create a mock task for testing."""
    task = Mock()
    task.id = "task-123"
    task.domain = domain
    task.description = "Test task"
    task.result_type = "image"
    task.retry_count = 0
    task.created_at = datetime.now()
    task.status = status
    return task
