"""
Advanced Analytics Dashboard with Predictive Insights

This module provides comprehensive analytics and predictive insights for the ArbitrageAI platform.
It includes real-time metrics, trend analysis, predictive modeling, and business intelligence features.

Features:
- Real-time system metrics and KPIs
- Predictive analytics for task completion times and success rates
- Revenue forecasting and trend analysis
- Performance optimization recommendations
- Anomaly detection and alerting
- Custom dashboard widgets and visualizations
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict
from decimal import Decimal
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, and_, or_, desc, asc
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from src.api.database import get_db
from src.api.models import Task, TaskStatus, Bid, BidStatus
from src.utils.logger import get_logger
from src.utils.telemetry import get_tracer
from src.config import Config

# Import telemetry
from traceloop.sdk.decorators import task, workflow

# Initialize logger and telemetry
logger = get_logger(__name__)
tracer = get_tracer(__name__)

# Router setup
router = APIRouter(
    prefix="/api/analytics",
    tags=["analytics"],
    responses={404: {"description": "Not found"}}
)


# Pydantic models for API responses
class KPIResponse(BaseModel):
    """Key Performance Indicators response model."""
    total_revenue: float
    total_tasks: int
    success_rate: float
    avg_completion_time: float
    active_users: int
    revenue_growth_rate: float
    tasks_per_hour: float


class PredictiveInsight(BaseModel):
    """Predictive insight model."""
    metric: str
    prediction: float
    confidence: float
    trend: str  # "up", "down", "stable"
    time_horizon: str
    explanation: str


class AnomalyAlert(BaseModel):
    """Anomaly detection alert model."""
    metric: str
    value: float
    expected_range: Tuple[float, float]
    severity: str  # "low", "medium", "high", "critical"
    timestamp: datetime
    description: str


class PerformanceMetric(BaseModel):
    """Performance metric model."""
    name: str
    value: float
    unit: str
    trend: float
    target: Optional[float] = None


class DashboardWidget(BaseModel):
    """Dashboard widget configuration."""
    id: str
    type: str  # "chart", "metric", "table", "heatmap"
    title: str
    data_source: str
    configuration: Dict[str, Any]


class AnalyticsSummary(BaseModel):
    """Comprehensive analytics summary."""
    kpis: KPIResponse
    predictive_insights: List[PredictiveInsight]
    anomalies: List[AnomalyAlert]
    performance_metrics: List[PerformanceMetric]
    recommendations: List[str]
    last_updated: datetime


@dataclass
class TimeSeriesData:
    """Time series data for analytics."""
    timestamps: List[datetime]
    values: List[float]
    labels: List[str]


@dataclass
class PredictionResult:
    """Prediction result with confidence intervals."""
    prediction: float
    lower_bound: float
    upper_bound: float
    confidence: float
    model_accuracy: float


class AnalyticsEngine:
    """Core analytics engine for processing and analyzing platform data."""
    
    def __init__(self, db: Session):
        """
        Initialize the analytics engine.
        
        Args:
            db: Database session
        """
        self.db = db
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes
        self.prediction_models = {}
        
    def _get_cache_key(self, query_type: str, params: Dict[str, Any]) -> str:
        """Generate cache key for query results."""
        return f"{query_type}:{hash(json.dumps(params, sort_keys=True))}"
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self.cache:
            return False
        
        cached_data = self.cache[cache_key]
        return (datetime.now() - cached_data['timestamp']).total_seconds() < self.cache_ttl
    
    def _cache_result(self, cache_key: str, result: Any):
        """Cache query result."""
        self.cache[cache_key] = {
            'result': result,
            'timestamp': datetime.now()
        }
    
    def _get_cached_result(self, cache_key: str):
        """Get cached result if valid."""
        if self._is_cache_valid(cache_key):
            return self.cache[cache_key]['result']
        return None

    def _calculate_task_count(self, time_filter: datetime) -> int:
        """Calculate total task count."""
        return self.db.query(Task).filter(
            Task.created_at >= time_filter
        ).count()
    
    def _calculate_success_rate(self, time_filter: datetime) -> float:
        """Calculate task success rate."""
        total_tasks = self._calculate_task_count(time_filter)
        if total_tasks == 0:
            return 0.0
        
        completed_tasks = self.db.query(Task).filter(
            Task.created_at >= time_filter,
            Task.status == TaskStatus.COMPLETED
        ).count()
        
        return (completed_tasks / total_tasks) * 100
    
    def _calculate_avg_completion_time(self, time_filter: datetime) -> float:
        """Calculate average task completion time in hours."""
        tasks = self.db.query(Task).filter(
            Task.created_at >= time_filter,
            Task.status == TaskStatus.COMPLETED,
            Task.completed_at.isnot(None)
        ).all()
        
        if not tasks:
            return 0.0
        
        total_time = 0
        for task in tasks:
            if task.completed_at:
                completion_time = (task.completed_at - task.created_at).total_seconds()
                total_time += completion_time
        
        avg_seconds = total_time / len(tasks)
        return avg_seconds / 3600  # Convert to hours


class KPIAnalytics(AnalyticsEngine):
    """Key Performance Indicators analytics."""
    
    @task(name="calculate_kpis")
    def calculate_kpis(self, time_range: str = "24h") -> KPIResponse:
        """
        Calculate key performance indicators.
        
        Args:
            time_range: Time range for calculation ("24h", "7d", "30d", "all")
            
        Returns:
            KPI response with calculated metrics
        """
        cache_key = self._get_cache_key("kpis", {"time_range": time_range})
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            return cached_result
        
        # Calculate time filter
        time_filter = self._get_time_filter(time_range)
        
        # Calculate metrics
        total_revenue = self._calculate_revenue(time_filter)
        total_tasks = self._calculate_task_count(time_filter)
        success_rate = self._calculate_success_rate(time_filter)
        avg_completion_time = self._calculate_avg_completion_time(time_filter)
        active_users = self._calculate_active_users(time_filter)
        revenue_growth_rate = self._calculate_revenue_growth_rate(time_filter)
        tasks_per_hour = self._calculate_tasks_per_hour(time_filter)
        
        kpis = KPIResponse(
            total_revenue=total_revenue,
            total_tasks=total_tasks,
            success_rate=success_rate,
            avg_completion_time=avg_completion_time,
            active_users=active_users,
            revenue_growth_rate=revenue_growth_rate,
            tasks_per_hour=tasks_per_hour
        )
        
        self._cache_result(cache_key, kpis)
        return kpis
    
    def _get_time_filter(self, time_range: str) -> datetime:
        """Get time filter for queries."""
        now = datetime.now()
        if time_range == "24h":
            return now - timedelta(hours=24)
        elif time_range == "7d":
            return now - timedelta(days=7)
        elif time_range == "30d":
            return now - timedelta(days=30)
        else:
            return now - timedelta(days=365)  # Default to 1 year
    
    def _calculate_revenue(self, time_filter: datetime) -> float:
        """Calculate total revenue."""
        result = self.db.query(func.sum(Task.amount_paid)).filter(
            Task.created_at >= time_filter,
            Task.amount_paid.isnot(None),
            Task.status == TaskStatus.COMPLETED
        ).scalar()
        return float(result or 0) / 100  # Convert cents to dollars
    
    def _calculate_active_users(self, time_filter: datetime) -> int:
        """Calculate number of active users."""
        return self.db.query(func.count(func.distinct(Task.client_email))).filter(
            Task.created_at >= time_filter,
            Task.client_email.isnot(None)
        ).scalar() or 0
    
    def _calculate_revenue_growth_rate(self, time_filter: datetime) -> float:
        """Calculate revenue growth rate."""
        current_revenue = self._calculate_revenue(time_filter)
        
        # Calculate previous period revenue
        period_length = datetime.now() - time_filter
        previous_start = time_filter - period_length
        previous_revenue = self._calculate_revenue(previous_start)
        
        if previous_revenue == 0:
            return 0.0
        
        growth_rate = ((current_revenue - previous_revenue) / previous_revenue) * 100
        return growth_rate
    
    def _calculate_tasks_per_hour(self, time_filter: datetime) -> float:
        """Calculate average tasks per hour."""
        total_tasks = self._calculate_task_count(time_filter)
        hours = (datetime.now() - time_filter).total_seconds() / 3600
        
        if hours < 0.0001:  # Avoid division by zero or near-zero
            return 0.0
        
        return total_tasks / hours


class PredictiveAnalytics(AnalyticsEngine):
    """Predictive analytics for forecasting and trend analysis."""
    
    @task(name="generate_predictions")
    def generate_predictions(self, metric: str, horizon_hours: int = 24) -> PredictionResult:
        """
        Generate predictions for a specific metric.
        
        Args:
            metric: Metric to predict ("revenue", "tasks", "success_rate")
            horizon_hours: Prediction horizon in hours
            
        Returns:
            Prediction result with confidence intervals
        """
        cache_key = self._get_cache_key("prediction", {"metric": metric, "horizon": horizon_hours})
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            return cached_result
        
        # Get historical data
        historical_data = self._get_historical_data(metric, horizon_hours * 7)  # Use 7x horizon for training
        
        if len(historical_data.values) < 10:  # Need minimum data points
            return PredictionResult(
                prediction=0.0,
                lower_bound=0.0,
                upper_bound=0.0,
                confidence=0.0,
                model_accuracy=0.0
            )
        
        # Train prediction model
        model, accuracy = self._train_prediction_model(historical_data)
        
        # Generate prediction
        prediction = self._make_prediction(model, horizon_hours)
        
        # Calculate confidence intervals
        confidence_interval = self._calculate_confidence_interval(model, historical_data, prediction)
        
        result = PredictionResult(
            prediction=prediction,
            lower_bound=confidence_interval[0],
            upper_bound=confidence_interval[1],
            confidence=0.8,  # Placeholder confidence
            model_accuracy=accuracy
        )
        
        self._cache_result(cache_key, result)
        return result
    
    def _get_historical_data(self, metric: str, hours: int) -> TimeSeriesData:
        """Get historical data for a metric."""
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        
        if metric == "revenue":
            # Group by hour and sum revenue
            query = self.db.query(
                func.date_trunc('hour', Task.created_at).label('hour'),
                func.sum(Task.amount_paid).label('revenue')
            ).filter(
                Task.created_at >= start_time,
                Task.created_at <= end_time,
                Task.amount_paid.isnot(None),
                Task.status == TaskStatus.COMPLETED
            ).group_by(
                func.date_trunc('hour', Task.created_at)
            ).order_by('hour')
            
            results = query.all()
            timestamps = [row.hour for row in results]
            values = [float(row.revenue or 0) / 100 for row in results]
            labels = [f"Hour {i}" for i in range(len(results))]
            
        elif metric == "tasks":
            # Group by hour and count tasks
            query = self.db.query(
                func.date_trunc('hour', Task.created_at).label('hour'),
                func.count(Task.id).label('task_count')
            ).filter(
                Task.created_at >= start_time,
                Task.created_at <= end_time
            ).group_by(
                func.date_trunc('hour', Task.created_at)
            ).order_by('hour')
            
            results = query.all()
            timestamps = [row.hour for row in results]
            values = [float(row.task_count) for row in results]
            labels = [f"Hour {i}" for i in range(len(results))]
            
        else:  # success_rate
            # Calculate success rate by hour
            query = self.db.query(
                func.date_trunc('hour', Task.created_at).label('hour'),
                func.count(Task.id).label('total_tasks'),
                func.sum(
                    case([(Task.status == TaskStatus.COMPLETED, 1)], else_=0)
                ).label('completed_tasks')
            ).filter(
                Task.created_at >= start_time,
                Task.created_at <= end_time
            ).group_by(
                func.date_trunc('hour', Task.created_at)
            ).order_by('hour')
            
            results = query.all()
            timestamps = [row.hour for row in results]
            values = []
            for row in results:
                if row.total_tasks > 0:
                    success_rate = (row.completed_tasks / row.total_tasks) * 100
                else:
                    success_rate = 0.0
                values.append(success_rate)
            labels = [f"Hour {i}" for i in range(len(results))]
        
        return TimeSeriesData(timestamps=timestamps, values=values, labels=labels)
    
    def _train_prediction_model(self, data: TimeSeriesData) -> Tuple[LinearRegression, float]:
        """Train a prediction model using historical data."""
        if len(data.values) < 5:
            return LinearRegression(), 0.0
        
        # Prepare features (time index)
        X = np.array(range(len(data.values))).reshape(-1, 1)
        y = np.array(data.values)
        
        # Split data for training and testing
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        # Train model
        model = LinearRegression()
        model.fit(X_train, y_train)
        
        # Calculate accuracy
        accuracy = model.score(X_test, y_test)
        
        return model, accuracy
    
    def _make_prediction(self, model: LinearRegression, horizon_hours: int) -> float:
        """Make prediction for future time point."""
        # Predict for the next time point
        future_time = np.array([[horizon_hours]])
        prediction = model.predict(future_time)
        return float(prediction[0])
    
    def _calculate_confidence_interval(self, model: LinearRegression, data: TimeSeriesData, prediction: float) -> Tuple[float, float]:
        """Calculate confidence interval for prediction."""
        # Simple confidence interval based on historical variance
        if len(data.values) < 2:
            return prediction * 0.9, prediction * 1.1
        
        std_dev = np.std(data.values)
        margin_of_error = 1.96 * std_dev  # 95% confidence
        
        return prediction - margin_of_error, prediction + margin_of_error


class AnomalyDetection(AnalyticsEngine):
    """Anomaly detection for identifying unusual patterns."""
    
    @task(name="detect_anomalies")
    def detect_anomalies(self, metric: str, time_range: str = "24h") -> List[AnomalyAlert]:
        """
        Detect anomalies in a specific metric.
        
        Args:
            metric: Metric to analyze ("revenue", "tasks", "success_rate")
            time_range: Time range for analysis
            
        Returns:
            List of anomaly alerts
        """
        cache_key = self._get_cache_key("anomalies", {"metric": metric, "time_range": time_range})
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            return cached_result
        
        # Get recent data
        time_filter = self._get_time_filter(time_range)
        recent_data = self._get_recent_data(metric, time_filter)
        
        if len(recent_data) < 20:  # Need sufficient data for anomaly detection
            return []
        
        # Detect anomalies using Isolation Forest
        anomalies = self._detect_isolation_forest_anomalies(recent_data)
        
        # Convert to alerts
        alerts = []
        for anomaly in anomalies:
            alert = AnomalyAlert(
                metric=metric,
                value=anomaly['value'],
                expected_range=anomaly['expected_range'],
                severity=anomaly['severity'],
                timestamp=anomaly['timestamp'],
                description=anomaly['description']
            )
            alerts.append(alert)
        
        self._cache_result(cache_key, alerts)
        return alerts
    
    def _get_recent_data(self, metric: str, time_filter: datetime) -> List[float]:
        """Get recent data points for anomaly detection."""
        if metric == "revenue":
            query = self.db.query(
                func.sum(Task.amount_paid).label('revenue')
            ).filter(
                Task.created_at >= time_filter,
                Task.amount_paid.isnot(None),
                Task.status == TaskStatus.COMPLETED
            ).group_by(
                func.date_trunc('hour', Task.created_at)
            ).order_by(desc('revenue'))
            
        elif metric == "tasks":
            query = self.db.query(
                func.count(Task.id).label('task_count')
            ).filter(
                Task.created_at >= time_filter
            ).group_by(
                func.date_trunc('hour', Task.created_at)
            ).order_by(desc('task_count'))
            
        else:  # success_rate
            query = self.db.query(
                (func.sum(
                    case([(Task.status == TaskStatus.COMPLETED, 1)], else_=0)
                ) * 100.0 / func.count(Task.id)).label('success_rate')
            ).filter(
                Task.created_at >= time_filter
            ).group_by(
                func.date_trunc('hour', Task.created_at)
            ).order_by(desc('success_rate'))
        
        results = query.all()
        return [float(row[0] or 0) for row in results]
    
    def _detect_isolation_forest_anomalies(self, data: List[float]) -> List[Dict[str, Any]]:
        """Detect anomalies using Isolation Forest algorithm."""
        if len(data) < 20:
            return []
        
        # Prepare data
        X = np.array(data).reshape(-1, 1)
        
        # Train Isolation Forest
        isolation_forest = IsolationForest(contamination=0.1, random_state=42)
        anomaly_labels = isolation_forest.fit_predict(X)
        
        # Find anomalies (label = -1)
        anomalies = []
        for i, label in enumerate(anomaly_labels):
            if label == -1:  # Anomaly detected
                value = data[i]
                # Calculate expected range based on normal data
                normal_data = [x for j, x in enumerate(data) if anomaly_labels[j] == 1]
                if normal_data:
                    mean = np.mean(normal_data)
                    std = np.std(normal_data)
                    expected_range = (mean - 2*std, mean + 2*std)
                    
                    # Determine severity
                    if abs(value - mean) > 3 * std:
                        severity = "critical"
                    elif abs(value - mean) > 2 * std:
                        severity = "high"
                    elif abs(value - mean) > std:
                        severity = "medium"
                    else:
                        severity = "low"
                    
                    anomalies.append({
                        'value': value,
                        'expected_range': expected_range,
                        'severity': severity,
                        'timestamp': datetime.now(),  # Would need actual timestamp from data
                        'description': f"Anomalous {value} outside expected range {expected_range}"
                    })
        
        return anomalies


class PerformanceAnalytics(AnalyticsEngine):
    """Performance analytics and optimization recommendations."""
    
    @task(name="analyze_performance")
    def analyze_performance(self) -> List[PerformanceMetric]:
        """
        Analyze system performance and generate metrics.
        
        Returns:
            List of performance metrics
        """
        cache_key = self._get_cache_key("performance", {})
        cached_result = self._get_cached_result(cache_key)
        if cached_result:
            return cached_result
        
        metrics = []
        
        # Task processing performance
        task_metrics = self._analyze_task_performance()
        metrics.extend(task_metrics)
        
        # System resource utilization
        resource_metrics = self._analyze_resource_utilization()
        metrics.extend(resource_metrics)
        
        # User experience metrics
        ux_metrics = self._analyze_user_experience()
        metrics.extend(ux_metrics)
        
        self._cache_result(cache_key, metrics)
        return metrics
    
    def _analyze_task_performance(self) -> List[PerformanceMetric]:
        """Analyze task processing performance."""
        metrics = []
        
        # Average task completion time
        avg_completion_time = self._calculate_avg_completion_time(datetime.now() - timedelta(days=7))
        metrics.append(PerformanceMetric(
            name="avg_completion_time",
            value=avg_completion_time,
            unit="hours",
            trend=0.0,  # Would calculate trend over time
            target=2.0  # Target: complete tasks within 2 hours
        ))
        
        # Task success rate
        success_rate = self._calculate_success_rate(datetime.now() - timedelta(days=7))
        metrics.append(PerformanceMetric(
            name="success_rate",
            value=success_rate,
            unit="%",
            trend=0.0,
            target=95.0  # Target: 95% success rate
        ))
        
        # Task queue length
        queue_length = self._calculate_queue_length()
        metrics.append(PerformanceMetric(
            name="queue_length",
            value=queue_length,
            unit="tasks",
            trend=0.0,
            target=10.0  # Target: keep queue under 10 tasks
        ))
        
        return metrics
    
    def _analyze_resource_utilization(self) -> List[PerformanceMetric]:
        """Analyze system resource utilization."""
        metrics = []
        
        # Database query performance
        avg_query_time = self._calculate_avg_query_time()
        metrics.append(PerformanceMetric(
            name="avg_query_time",
            value=avg_query_time,
            unit="ms",
            trend=0.0,
            target=100.0  # Target: queries under 100ms
        ))
        
        # API response time
        avg_response_time = self._calculate_avg_response_time()
        metrics.append(PerformanceMetric(
            name="avg_response_time",
            value=avg_response_time,
            unit="ms",
            trend=0.0,
            target=500.0  # Target: responses under 500ms
        ))
        
        return metrics
    
    def _analyze_user_experience(self) -> List[PerformanceMetric]:
        """Analyze user experience metrics."""
        metrics = []
        
        # User satisfaction (based on task completion and time)
        satisfaction_score = self._calculate_user_satisfaction()
        metrics.append(PerformanceMetric(
            name="user_satisfaction",
            value=satisfaction_score,
            unit="score",
            trend=0.0,
            target=8.0  # Target: 8/10 satisfaction
        ))
        
        # Dashboard load time
        dashboard_load_time = self._calculate_dashboard_load_time()
        metrics.append(PerformanceMetric(
            name="dashboard_load_time",
            value=dashboard_load_time,
            unit="ms",
            trend=0.0,
            target=2000.0  # Target: dashboard loads in under 2 seconds
        ))
        
        return metrics
    
    def _calculate_queue_length(self) -> int:
        """Calculate current task queue length."""
        return self.db.query(Task).filter(
            Task.status.in_([TaskStatus.PENDING, TaskStatus.PAID])
        ).count()
    
    def _calculate_avg_query_time(self) -> float:
        """Calculate average database query time (placeholder)."""
        # This would integrate with actual query performance monitoring
        return 50.0  # Placeholder value
    
    def _calculate_avg_response_time(self) -> float:
        """Calculate average API response time (placeholder)."""
        # This would integrate with actual response time monitoring
        return 200.0  # Placeholder value
    
    def _calculate_user_satisfaction(self) -> float:
        """Calculate user satisfaction score (placeholder)."""
        # This would integrate with actual user feedback and metrics
        return 8.5  # Placeholder value
    
    def _calculate_dashboard_load_time(self) -> float:
        """Calculate dashboard load time (placeholder)."""
        # This would integrate with actual frontend performance monitoring
        return 1500.0  # Placeholder value


class AnalyticsAPI:
    """Main analytics API class combining all analytics engines."""
    
    def __init__(self, db: Session):
        """
        Initialize the analytics API.
        
        Args:
            db: Database session
        """
        self.kpi_analytics = KPIAnalytics(db)
        self.predictive_analytics = PredictiveAnalytics(db)
        self.anomaly_detection = AnomalyDetection(db)
        self.performance_analytics = PerformanceAnalytics(db)
    
    @task(name="get_analytics_summary")
    def get_analytics_summary(self, time_range: str = "24h") -> AnalyticsSummary:
        """
        Get comprehensive analytics summary.
        
        Args:
            time_range: Time range for analysis
            
        Returns:
            Comprehensive analytics summary
        """
        # Get KPIs
        kpis = self.kpi_analytics.calculate_kpis(time_range)
        
        # Get predictive insights
        predictive_insights = self._generate_predictive_insights()
        
        # Get anomalies
        anomalies = self._get_anomalies_summary()
        
        # Get performance metrics
        performance_metrics = self.performance_analytics.analyze_performance()
        
        # Generate recommendations
        recommendations = self._generate_recommendations(kpis, performance_metrics)
        
        return AnalyticsSummary(
            kpis=kpis,
            predictive_insights=predictive_insights,
            anomalies=anomalies,
            performance_metrics=performance_metrics,
            recommendations=recommendations,
            last_updated=datetime.now()
        )
    
    def _generate_predictive_insights(self) -> List[PredictiveInsight]:
        """Generate predictive insights for key metrics."""
        insights = []
        
        # Predict revenue for next 24 hours
        revenue_prediction = self.predictive_analytics.generate_predictions("revenue", 24)
        insights.append(PredictiveInsight(
            metric="revenue",
            prediction=revenue_prediction.prediction,
            confidence=revenue_prediction.confidence,
            trend="up" if revenue_prediction.prediction > 0 else "down",
            time_horizon="24h",
            explanation="Based on historical revenue patterns and current trends"
        ))
        
        # Predict task volume for next 7 days
        tasks_prediction = self.predictive_analytics.generate_predictions("tasks", 168)  # 7 days
        insights.append(PredictiveInsight(
            metric="tasks",
            prediction=tasks_prediction.prediction,
            confidence=tasks_prediction.confidence,
            trend="stable",
            time_horizon="7d",
            explanation="Based on historical task submission patterns"
        ))
        
        return insights
    
    def _get_anomalies_summary(self) -> List[AnomalyAlert]:
        """Get summary of recent anomalies."""
        anomalies = []
        
        # Check for revenue anomalies
        revenue_anomalies = self.anomaly_detection.detect_anomalies("revenue", "24h")
        anomalies.extend(revenue_anomalies)
        
        # Check for task volume anomalies
        task_anomalies = self.anomaly_detection.detect_anomalies("tasks", "24h")
        anomalies.extend(task_anomalies)
        
        return anomalies
    
    def _generate_recommendations(self, kpis: KPIResponse, performance_metrics: List[PerformanceMetric]) -> List[str]:
        """Generate actionable recommendations based on analytics."""
        recommendations = []
        
        # Revenue recommendations
        if kpis.revenue_growth_rate < 0:
            recommendations.append("Revenue is declining. Consider reviewing pricing strategy and marketing efforts.")
        
        if kpis.success_rate < 90:
            recommendations.append("Task success rate is below target. Review task execution processes and quality control.")
        
        # Performance recommendations
        for metric in performance_metrics:
            if metric.name == "avg_completion_time" and metric.value > metric.target:
                recommendations.append(f"Task completion time ({metric.value:.1f}h) exceeds target ({metric.target}h). Optimize task processing pipeline.")
            
            elif metric.name == "queue_length" and metric.value > metric.target:
                recommendations.append(f"Task queue length ({metric.value}) is high. Consider scaling resources or optimizing task distribution.")
        
        # Default recommendations
        if not recommendations:
            recommendations.append("System performance is within acceptable ranges. Continue monitoring for optimization opportunities.")
        
        return recommendations


# API endpoints
@router.get("/kpis", response_model=KPIResponse)
@task(name="get_kpis_endpoint")
async def get_kpis(
    time_range: str = Query("24h", description="Time range: 24h, 7d, 30d, all"),
    db: Session = Depends(get_db)
):
    """
    Get key performance indicators.
    
    Args:
        time_range: Time range for KPI calculation
        db: Database session
        
    Returns:
        KPI response with calculated metrics
    """
    try:
        kpi_analytics = KPIAnalytics(db)
        return kpi_analytics.calculate_kpis(time_range)
    except Exception as e:
        logger.error(f"Failed to calculate KPIs: {e}")
        raise HTTPException(status_code=500, detail="Failed to calculate KPIs")


@router.get("/predictions/{metric}", response_model=PredictionResult)
@task(name="get_predictions_endpoint")
async def get_predictions(
    metric: str,
    horizon_hours: int = Query(24, description="Prediction horizon in hours"),
    db: Session = Depends(get_db)
):
    """
    Get predictions for a specific metric.
    
    Args:
        metric: Metric to predict (revenue, tasks, success_rate)
        horizon_hours: Prediction horizon in hours
        db: Database session
        
    Returns:
        Prediction result with confidence intervals
    """
    try:
        predictive_analytics = PredictiveAnalytics(db)
        return predictive_analytics.generate_predictions(metric, horizon_hours)
    except Exception as e:
        logger.error(f"Failed to generate predictions: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate predictions")


@router.get("/anomalies/{metric}", response_model=List[AnomalyAlert])
@task(name="get_anomalies_endpoint")
async def get_anomalies(
    metric: str,
    time_range: str = Query("24h", description="Time range for anomaly detection"),
    db: Session = Depends(get_db)
):
    """
    Get anomalies for a specific metric.
    
    Args:
        metric: Metric to analyze (revenue, tasks, success_rate)
        time_range: Time range for analysis
        db: Database session
        
    Returns:
        List of anomaly alerts
    """
    try:
        anomaly_detection = AnomalyDetection(db)
        return anomaly_detection.detect_anomalies(metric, time_range)
    except Exception as e:
        logger.error(f"Failed to detect anomalies: {e}")
        raise HTTPException(status_code=500, detail="Failed to detect anomalies")


@router.get("/performance", response_model=List[PerformanceMetric])
@task(name="get_performance_endpoint")
async def get_performance(
    db: Session = Depends(get_db)
):
    """
    Get performance metrics.
    
    Args:
        db: Database session
        
    Returns:
        List of performance metrics
    """
    try:
        performance_analytics = PerformanceAnalytics(db)
        return performance_analytics.analyze_performance()
    except Exception as e:
        logger.error(f"Failed to analyze performance: {e}")
        raise HTTPException(status_code=500, detail="Failed to analyze performance")


@router.get("/summary", response_model=AnalyticsSummary)
@task(name="get_analytics_summary_endpoint")
async def get_analytics_summary(
    time_range: str = Query("24h", description="Time range for analysis"),
    db: Session = Depends(get_db)
):
    """
    Get comprehensive analytics summary.
    
    Args:
        time_range: Time range for analysis
        db: Database session
        
    Returns:
        Comprehensive analytics summary
    """
    try:
        analytics_api = AnalyticsAPI(db)
        return analytics_api.get_analytics_summary(time_range)
    except Exception as e:
        logger.error(f"Failed to get analytics summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to get analytics summary")


@router.get("/recommendations", response_model=List[str])
@task(name="get_recommendations_endpoint")
async def get_recommendations(
    db: Session = Depends(get_db)
):
    """
    Get actionable recommendations based on analytics.
    
    Args:
        db: Database session
        
    Returns:
        List of recommendations
    """
    try:
        analytics_api = AnalyticsAPI(db)
        summary = analytics_api.get_analytics_summary()
        return summary.recommendations
    except Exception as e:
        logger.error(f"Failed to get recommendations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get recommendations")


@router.get("/widgets", response_model=List[DashboardWidget])
@task(name="get_dashboard_widgets_endpoint")
async def get_dashboard_widgets(
    db: Session = Depends(get_db)
):
    """
    Get configured dashboard widgets.
    
    Args:
        db: Database session
        
    Returns:
        List of dashboard widget configurations
    """
    # This would typically load from a configuration database
    # For now, return default widgets
    widgets = [
        DashboardWidget(
            id="kpi_overview",
            type="metric",
            title="Key Performance Indicators",
            data_source="kpis",
            configuration={"time_range": "24h"}
        ),
        DashboardWidget(
            id="revenue_trend",
            type="chart",
            title="Revenue Trend",
            data_source="revenue",
            configuration={"chart_type": "line", "time_range": "7d"}
        ),
        DashboardWidget(
            id="task_completion",
            type="chart",
            title="Task Completion Rate",
            data_source="success_rate",
            configuration={"chart_type": "bar", "time_range": "7d"}
        ),
        DashboardWidget(
            id="anomalies",
            type="table",
            title="Recent Anomalies",
            data_source="anomalies",
            configuration={"limit": 10}
        )
    ]
    
    return widgets


# Background tasks for analytics
@task(name="update_analytics_cache")
async def update_analytics_cache():
    """
    Background task to update analytics cache periodically.
    """
    # This would be called by a scheduler to keep analytics data fresh
    logger.info("Updating analytics cache...")
    # Implementation would depend on the scheduling system used


def register_analytics_routes(app):
    """Register analytics routes with the FastAPI application."""
    app.include_router(router)