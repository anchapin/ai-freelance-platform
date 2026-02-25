import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import './TaskStatus.css';

const API_BASE_URL = 'http://localhost:8000';

function TaskStatus() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const clientEmail = searchParams.get('email');
  
  const [task, setTask] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Client dashboard state
  const [dashboardData, setDashboardData] = useState(null);
  const [showDashboard, setShowDashboard] = useState(false);
  const [emailInput, setEmailInput] = useState(clientEmail || '');

  // Polling configuration with exponential backoff
  const POLL_INTERVALS = [2000, 3000, 5000, 8000, 10000]; // 2s, 3s, 5s, 8s, 10s
  const STOP_POLLING_STATES = ['COMPLETED', 'FAILED', 'CANCELLED'];

  // Fetch dashboard data when email is provided (requires authentication token)
  const fetchDashboardData = async (email) => {
    if (!email || !email.includes('@')) return;
    
    try {
      // Get stored token from localStorage (generated at checkout)
      const storedToken = localStorage.getItem(`client_token_${email}`);
      
      // Build URL with email and token (token is required for authentication)
      let url = `${API_BASE_URL}/api/client/history?email=${encodeURIComponent(email)}`;
      if (storedToken) {
        url += `&token=${encodeURIComponent(storedToken)}`;
      } else {
        // If no token, request will be rejected with 403
        console.warn(`No authentication token found for ${email}. Dashboard access denied.`);
        return;
      }
      
      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        setDashboardData(data);
      } else if (response.status === 403) {
        console.error('Invalid or missing authentication token for dashboard access');
      }
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err);
    }
  };

  useEffect(() => {
    if (clientEmail) {
      setEmailInput(clientEmail);
      fetchDashboardData(clientEmail);
    }
  }, [clientEmail]);

  useEffect(() => {
    if (!taskId) {
      setLoading(false);
      return;
    }

    let pollIndex = 0;
    let timeoutId = null;

    const fetchTask = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/tasks/${taskId}`);
        
        if (!response.ok) {
          if (response.status === 404) {
            throw new Error('Task not found');
          }
          throw new Error('Failed to fetch task');
        }
        
        const data = await response.json();
        setTask(data);
        setError(null);

        // Stop polling if task is in a terminal state
        if (STOP_POLLING_STATES.includes(data.status)) {
          setLoading(false);
          if (timeoutId) clearTimeout(timeoutId);
          return;
        }

        // Exponential backoff: increase interval between polls
        pollIndex = Math.min(pollIndex + 1, POLL_INTERVALS.length - 1);
        const nextInterval = POLL_INTERVALS[pollIndex];
        
        timeoutId = setTimeout(fetchTask, nextInterval);
      } catch (err) {
        setError(err.message);
        setLoading(false);
      }
    };

    // Initial fetch
    fetchTask();

    // Cleanup on unmount
    return () => {
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [taskId]);

  // Handle email submission for dashboard
  const handleEmailSubmit = (e) => {
    e.preventDefault();
    if (emailInput && emailInput.includes('@')) {
      fetchDashboardData(emailInput);
      setShowDashboard(true);
    }
  };

  // Handle case where no task ID is provided - show dashboard instead
  if (!taskId) {
    return (
      <div className="task-status">
        <div className="dashboard-container">
          {/* Email Input Section */}
          <div className="dashboard-header">
            <h1>Client Dashboard</h1>
            <p>View your task history and track your orders</p>
          </div>
          
          <div className="email-lookup">
            <form onSubmit={handleEmailSubmit}>
              <input
                type="email"
                placeholder="Enter your email to view history"
                value={emailInput}
                onChange={(e) => setEmailInput(e.target.value)}
                required
              />
              <button type="submit">View Dashboard</button>
            </form>
          </div>

          {/* Dashboard Data Display */}
          {dashboardData && (
            <div className="dashboard-content">
              {/* Stats Cards */}
              <div className="stats-grid">
                <div className="stat-card">
                  <div className="stat-value">{dashboardData.stats.total_tasks}</div>
                  <div className="stat-label">Total Tasks</div>
                </div>
                <div className="stat-card completed">
                  <div className="stat-value">{dashboardData.stats.completed_tasks}</div>
                  <div className="stat-label">Completed</div>
                </div>
                <div className="stat-card in-progress">
                  <div className="stat-value">{dashboardData.stats.in_progress_tasks}</div>
                  <div className="stat-label">In Progress</div>
                </div>
                <div className="stat-card spending">
                  <div className="stat-value">${dashboardData.stats.total_spent}</div>
                  <div className="stat-label">Total Spent</div>
                </div>
              </div>

              {/* Loyalty/Discount Section */}
              <div className="discount-section">
                <h3>🎁 Loyalty Rewards</h3>
                <div className="discount-info">
                  <div className="current-tier">
                    <span className="tier-badge">
                      {dashboardData.discount.current_tier === 0 ? 'New Client' :
                       dashboardData.discount.current_tier === 1 ? 'Returning Client' :
                       dashboardData.discount.current_tier === 2 ? 'Loyal Client' : 'VIP Client'}
                    </span>
                    <span className="discount-amount">
                      {dashboardData.discount.discount_percentage > 0 
                        ? `${dashboardData.discount.discount_percentage * 100}% off` 
                        : 'No discount'}
                    </span>
                  </div>
                  {dashboardData.next_discount && (
                    <div className="next-tier">
                      Complete {dashboardData.next_discount.tasks_needed} more task(s) for {dashboardData.next_discount.label}
                    </div>
                  )}
                </div>
              </div>

              {/* Task History List */}
              <div className="history-section">
                <h3>📋 Task History</h3>
                {dashboardData.tasks.length === 0 ? (
                  <p className="no-tasks">No tasks found. Submit your first task above!</p>
                ) : (
                  <div className="task-list">
                    {dashboardData.tasks.map((task) => (
                      <div key={task.id} className={`task-item status-${task.status.toLowerCase()}`}>
                        <div className="task-header">
                          <span className={`status-badge status-${task.status.toLowerCase()}`}>
                            {task.status}
                          </span>
                          <span className="task-date">
                            {new Date(task.id.split('-')[0], 0).toLocaleDateString()}
                          </span>
                        </div>
                        <div className="task-info">
                          <h4>{task.title}</h4>
                          <p className="task-domain">{task.domain}</p>
                        </div>
                        <div className="task-meta">
                          {task.amount_dollars && (
                            <span className="task-price">${task.amount_dollars}</span>
                          )}
                          {task.status === 'COMPLETED' && task.delivery_token && (
                            <a 
                              href={`/task-status?task_id=${task.id}&token=${task.delivery_token}`}
                              className="delivery-link"
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              🔗 View Result
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Handle loading and error states
  if (loading) {
    return (
      <div className="task-status">
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Loading task...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="task-status">
        <div className="error-container">
          <p className="error-message">{error}</p>
        </div>
      </div>
    );
  }

  // Render based on task status
  const renderContent = () => {
    switch (task.status) {
      case 'PENDING':
        return (
          <div className="status-container pending">
            <div className="status-icon">⏳</div>
            <h2>Task Pending Payment</h2>
            <p>Your task is waiting for payment to be processed.</p>
            <p className="task-id">Task ID: {task.id}</p>
          </div>
        );
      
      case 'PAID':
        return (
          <div className="status-container paid">
            <div className="spinner-container">
              <div className="spinner"></div>
            </div>
            <h2>Processing Your Task</h2>
            <p>Your payment has been confirmed. We are working on your task.</p>
            <p className="task-id">Task ID: {task.id}</p>
          </div>
        );
      
      case 'COMPLETED':
        const deliveryUrl = task.delivery_token 
          ? `/task-status?task_id=${task.id}&token=${task.delivery_token}`
          : null;
        return (
          <div className="status-container completed">
            <div className="status-icon">✅</div>
            <h2>Task Completed!</h2>
            {task.result_image_url ? (
              <div className="result-image-container">
                <img 
                  src={task.result_image_url} 
                  alt="Task Result" 
                  className="result-image"
                />
              </div>
            ) : (
              <p className="no-result">No result image available.</p>
            )}
            {deliveryUrl && (
              <a href={deliveryUrl} className="secure-delivery-link">
                🔗 Secure Delivery Link
              </a>
            )}
            <p className="task-id">Task ID: {task.id}</p>
          </div>
        );
      
      case 'FAILED':
        return (
          <div className="status-container failed">
            <div className="status-icon">❌</div>
            <h2>Task Failed</h2>
            <p>Unfortunately, your task could not be processed.</p>
            <p className="task-id">Task ID: {task.id}</p>
          </div>
        );
      
      default:
        return (
          <div className="status-container unknown">
            <p>Unknown status: {task.status}</p>
            <p className="task-id">Task ID: {task.id}</p>
          </div>
        );
    }
  };

  return (
    <div className="task-status">
      <div className="task-status-card">
        {renderContent()}
        
        {task && (
          <div className="task-details">
            <h3>Task Details</h3>
            <p><strong>Title:</strong> {task.title}</p>
            <p><strong>Domain:</strong> {task.domain}</p>
            <p><strong>Description:</strong> {task.description}</p>
            {task.amount_paid && (
              <p><strong>Amount Paid:</strong> ${(task.amount_paid / 100).toFixed(2)}</p>
            )}
          </div>
        )}
        
        {/* Quick Link to Dashboard */}
        <div className="dashboard-quick-link">
          <button onClick={() => setShowDashboard(!showDashboard)}>
            {showDashboard ? 'Hide Dashboard' : 'View My Dashboard'}
          </button>
        </div>
        
        {/* Show mini dashboard if toggled */}
        {showDashboard && emailInput && (
          <div className="mini-dashboard">
            <h4>Your Statistics</h4>
            {dashboardData ? (
              <div className="mini-stats">
                <div className="mini-stat">
                  <span className="value">{dashboardData.stats.completed_tasks}</span>
                  <span className="label">Completed</span>
                </div>
                <div className="mini-stat">
                  <span className="value">${dashboardData.stats.total_spent}</span>
                  <span className="label">Spent</span>
                </div>
                <div className="mini-stat">
                  <span className="value">{dashboardData.discount.discount_percentage * 100 || 0}%</span>
                  <span className="label">Discount</span>
                </div>
              </div>
            ) : (
              <p>Loading...</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default TaskStatus;
