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

  useEffect(() => {
    if (!taskId) {
      setError('No task ID provided');
      setLoading(false);
      return;
    }

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
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    // Initial fetch
    fetchTask();

    // Poll every 5 seconds
    const intervalId = setInterval(fetchTask, 5000);

    // Cleanup on unmount
    return () => clearInterval(intervalId);
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
