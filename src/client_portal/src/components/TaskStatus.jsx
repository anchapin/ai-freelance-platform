import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import './TaskStatus.css';

const API_BASE_URL = 'http://localhost:8000';

function TaskStatus() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  
  const [task, setTask] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Polling configuration with exponential backoff
  const POLL_INTERVALS = [2000, 3000, 5000, 8000, 10000]; // 2s, 3s, 5s, 8s, 10s
  const MAX_POLL_INTERVAL = 10000;
  const STOP_POLLING_STATES = ['COMPLETED', 'FAILED', 'CANCELLED'];

  useEffect(() => {
    if (!taskId) {
      setError('No task ID provided');
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

  // Handle case where no task ID is provided
  if (!taskId) {
    return (
      <div className="task-status">
        <div className="error-container">
          <p className="error-message">No task ID provided. Please check your URL.</p>
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
          </div>
        )}
      </div>
    </div>
  );
}

export default TaskStatus;
