import React, { useState, useEffect } from 'react';
import { Line, Bar, Doughnut, Radar } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  RadialLinearScale,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js';
import './AnalyticsDashboard.css';

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  RadialLinearScale,
  Title,
  Tooltip,
  Legend,
  Filler
);

const API_BASE_URL = 'http://localhost:8000';

const AnalyticsDashboard = () => {
  const [kpis, setKpis] = useState(null);
  const [predictions, setPredictions] = useState({});
  const [anomalies, setAnomalies] = useState([]);
  const [performanceMetrics, setPerformanceMetrics] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState('24h');
  const [selectedMetric, setSelectedMetric] = useState('revenue');

  // Chart configurations
  const chartOptions = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top',
      },
      title: {
        display: true,
        text: '',
      },
    },
    scales: {
      y: {
        beginAtZero: true,
      },
    },
  };

  useEffect(() => {
    fetchAnalyticsData();
  }, [timeRange]);

  const fetchAnalyticsData = async () => {
    setLoading(true);
    try {
      // Fetch KPIs
      const kpisResponse = await fetch(`${API_BASE_URL}/api/analytics/kpis?time_range=${timeRange}`);
      const kpisData = await kpisResponse.json();
      setKpis(kpisData);

      // Fetch predictions
      const revenuePredictionResponse = await fetch(`${API_BASE_URL}/api/analytics/predictions/revenue?horizon_hours=24`);
      const revenuePrediction = await revenuePredictionResponse.json();
      
      const tasksPredictionResponse = await fetch(`${API_BASE_URL}/api/analytics/predictions/tasks?horizon_hours=168`);
      const tasksPrediction = await tasksPredictionResponse.json();
      
      setPredictions({
        revenue: revenuePrediction,
        tasks: tasksPrediction
      });

      // Fetch anomalies
      const anomaliesResponse = await fetch(`${API_BASE_URL}/api/analytics/anomalies/${selectedMetric}?time_range=${timeRange}`);
      const anomaliesData = await anomaliesResponse.json();
      setAnomalies(anomaliesData);

      // Fetch performance metrics
      const performanceResponse = await fetch(`${API_BASE_URL}/api/analytics/performance`);
      const performanceData = await performanceResponse.json();
      setPerformanceMetrics(performanceData);

      // Fetch recommendations
      const recommendationsResponse = await fetch(`${API_BASE_URL}/api/analytics/recommendations`);
      const recommendationsData = await recommendationsResponse.json();
      setRecommendations(recommendationsData);

    } catch (error) {
      console.error('Error fetching analytics data:', error);
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      maximumFractionDigits: 0
    }).format(value);
  };

  const formatNumber = (value) => {
    return new Intl.NumberFormat('en-US').format(value);
  };

  const getSeverityColor = (severity) => {
    switch (severity) {
      case 'critical': return '#dc2626';
      case 'high': return '#ea580c';
      case 'medium': return '#d97706';
      case 'low': return '#22c55e';
      default: return '#6b7280';
    }
  };

  const getTrendIcon = (trend) => {
    switch (trend) {
      case 'up': return '📈';
      case 'down': return '📉';
      case 'stable': return '➡️';
      default: return '➖';
    }
  };

  // Chart data
  const revenueChartData = {
    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    datasets: [
      {
        label: 'Revenue',
        data: [1200, 1900, 3000, 5000, 2300, 3600, 4500],
        borderColor: 'rgb(59, 130, 246)',
        backgroundColor: 'rgba(59, 130, 246, 0.1)',
        tension: 0.4,
      },
    ],
  };

  const taskCompletionChartData = {
    labels: ['Pending', 'Paid', 'Completed', 'Failed'],
    datasets: [
      {
        label: 'Tasks',
        data: [15, 25, 120, 5],
        backgroundColor: [
          'rgba(59, 130, 246, 0.8)',
          'rgba(16, 185, 129, 0.8)',
          'rgba(245, 158, 11, 0.8)',
          'rgba(239, 68, 68, 0.8)',
        ],
      },
    ],
  };

  const performanceChartData = {
    labels: ['Completion Time', 'Success Rate', 'Queue Length', 'Response Time'],
    datasets: [
      {
        label: 'Current',
        data: [performanceMetrics.find(m => m.name === 'avg_completion_time')?.value || 2.5, 85, 8, 150],
        backgroundColor: 'rgba(59, 130, 246, 0.2)',
        borderColor: 'rgba(59, 130, 246, 1)',
        pointBackgroundColor: 'rgba(59, 130, 246, 1)',
      },
      {
        label: 'Target',
        data: [2, 95, 10, 100],
        backgroundColor: 'rgba(16, 185, 129, 0.2)',
        borderColor: 'rgba(16, 185, 129, 1)',
        pointBackgroundColor: 'rgba(16, 185, 129, 1)',
      },
    ],
  };

  if (loading) {
    return (
      <div className="analytics-dashboard">
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Loading analytics...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="analytics-dashboard">
      <div className="dashboard-header">
        <h1>📊 Analytics Dashboard</h1>
        <div className="time-range-selector">
          <label>Time Range:</label>
          <select value={timeRange} onChange={(e) => setTimeRange(e.target.value)}>
            <option value="24h">Last 24 Hours</option>
            <option value="7d">Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
            <option value="all">All Time</option>
          </select>
        </div>
      </div>

      {/* KPIs Section */}
      {kpis && (
        <div className="kpi-grid">
          <div className="kpi-card revenue">
            <div className="kpi-icon">💰</div>
            <div className="kpi-content">
              <h3>Total Revenue</h3>
              <div className="kpi-value">{formatCurrency(kpis.total_revenue)}</div>
              <div className="kpi-change">
                {getTrendIcon(kpis.revenue_growth_rate >= 0 ? 'up' : 'down')}
                {kpis.revenue_growth_rate >= 0 ? '+' : ''}{kpis.revenue_growth_rate.toFixed(1)}%
              </div>
            </div>
          </div>

          <div className="kpi-card tasks">
            <div className="kpi-icon">📋</div>
            <div className="kpi-content">
              <h3>Total Tasks</h3>
              <div className="kpi-value">{formatNumber(kpis.total_tasks)}</div>
              <div className="kpi-change">
                {getTrendIcon('stable')} {kpis.tasks_per_hour.toFixed(1)} tasks/hour
              </div>
            </div>
          </div>

          <div className="kpi-card success">
            <div className="kpi-icon">✅</div>
            <div className="kpi-content">
              <h3>Success Rate</h3>
              <div className="kpi-value">{kpis.success_rate.toFixed(1)}%</div>
              <div className="kpi-change">
                {getTrendIcon(kpis.success_rate >= 90 ? 'up' : 'down')}
                Target: 90%
              </div>
            </div>
          </div>

          <div className="kpi-card users">
            <div className="kpi-icon">👥</div>
            <div className="kpi-content">
              <h3>Active Users</h3>
              <div className="kpi-value">{formatNumber(kpis.active_users)}</div>
              <div className="kpi-change">
                {getTrendIcon('stable')} Avg completion: {kpis.avg_completion_time.toFixed(1)}h
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Charts Section */}
      <div className="charts-grid">
        <div className="chart-card">
          <h3>Revenue Trend</h3>
          <Line data={revenueChartData} options={chartOptions} />
        </div>

        <div className="chart-card">
          <h3>Task Completion Status</h3>
          <Doughnut data={taskCompletionChartData} />
        </div>

        <div className="chart-card">
          <h3>Performance Metrics</h3>
          <Radar data={performanceChartData} options={{ ...chartOptions, scales: { r: { beginAtZero: true } } }} />
        </div>
      </div>

      {/* Predictive Insights Section */}
      <div className="insights-section">
        <h2>🔮 Predictive Insights</h2>
        <div className="insights-grid">
          {predictions.revenue && (
            <div className="insight-card">
              <h3>Revenue Prediction (24h)</h3>
              <div className="insight-value">{formatCurrency(predictions.revenue.prediction)}</div>
              <div className="insight-details">
                <span className="insight-trend">{getTrendIcon(predictions.revenue.trend)}</span>
                <span className="insight-confidence">Confidence: {(predictions.revenue.confidence * 100).toFixed(0)}%</span>
              </div>
              <div className="insight-range">
                Range: {formatCurrency(predictions.revenue.lower_bound)} - {formatCurrency(predictions.revenue.upper_bound)}
              </div>
            </div>
          )}

          {predictions.tasks && (
            <div className="insight-card">
              <h3>Task Volume Prediction (7d)</h3>
              <div className="insight-value">{formatNumber(predictions.tasks.prediction)}</div>
              <div className="insight-details">
                <span className="insight-trend">{getTrendIcon(predictions.tasks.trend)}</span>
                <span className="insight-confidence">Confidence: {(predictions.tasks.confidence * 100).toFixed(0)}%</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Anomalies Section */}
      <div className="anomalies-section">
        <h2>⚠️ Anomaly Detection</h2>
        {anomalies.length > 0 ? (
          <div className="anomalies-grid">
            {anomalies.map((anomaly, index) => (
              <div key={index} className="anomaly-card">
                <div className="anomaly-header">
                  <span className="anomaly-metric">{anomaly.metric}</span>
                  <span 
                    className="anomaly-severity"
                    style={{ backgroundColor: getSeverityColor(anomaly.severity) }}
                  >
                    {anomaly.severity.toUpperCase()}
                  </span>
                </div>
                <div className="anomaly-value">{anomaly.value}</div>
                <div className="anomaly-range">
                  Expected: {anomaly.expected_range[0].toFixed(2)} - {anomaly.expected_range[1].toFixed(2)}
                </div>
                <div className="anomaly-description">{anomaly.description}</div>
                <div className="anomaly-time">{new Date(anomaly.timestamp).toLocaleString()}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="no-anomalies">
            <span className="no-anomalies-icon">✅</span>
            <p>No anomalies detected in the selected time range.</p>
          </div>
        )}
      </div>

      {/* Performance Metrics Section */}
      <div className="performance-section">
        <h2>⚡ Performance Metrics</h2>
        <div className="metrics-grid">
          {performanceMetrics.map((metric, index) => (
            <div key={index} className="metric-card">
              <div className="metric-header">
                <h4>{metric.name.replace(/_/g, ' ').toUpperCase()}</h4>
                <span className="metric-unit">{metric.unit}</span>
              </div>
              <div className="metric-value">{metric.value.toFixed(2)}</div>
              {metric.target && (
                <div className="metric-target">
                  Target: {metric.target} {metric.unit}
                  <div className="metric-progress">
                    <div 
                      className="metric-progress-bar"
                      style={{ 
                        width: `${Math.min((metric.value / metric.target) * 100, 100)}%`,
                        backgroundColor: metric.value <= metric.target ? '#10b981' : '#ef4444'
                      }}
                    ></div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Recommendations Section */}
      <div className="recommendations-section">
        <h2>💡 Recommendations</h2>
        {recommendations.length > 0 ? (
          <div className="recommendations-list">
            {recommendations.map((recommendation, index) => (
              <div key={index} className="recommendation-card">
                <span className="recommendation-icon">🎯</span>
                <p>{recommendation}</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="no-recommendations">
            <span className="no-recommendations-icon">🎉</span>
            <p>Great job! No recommendations at this time. Keep up the excellent work!</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default AnalyticsDashboard;