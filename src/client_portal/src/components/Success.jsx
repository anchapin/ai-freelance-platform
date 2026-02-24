import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const API_BASE_URL = 'http://localhost:8000';

function Success() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    // Get session_id from URL query parameter
    const sessionId = new URLSearchParams(window.location.search).get('session_id');

    if (!sessionId) {
      setError('No session ID provided');
      setLoading(false);
      return;
    }

    const fetchTaskId = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/session/${sessionId}`);
        
        if (!response.ok) {
          if (response.status === 404) {
            throw new Error('Task not found for this session');
          }
          throw new Error('Failed to fetch task');
        }
        
        const data = await response.json();
        
        // Redirect to task status page with the task_id
        navigate(`/task-status?task_id=${data.task_id}`);
      } catch (err) {
        setError(err.message);
        setLoading(false);
      }
    };

    fetchTaskId();
  }, [navigate]);

  if (loading) {
    return (
      <div className="success-page">
        <div className="loading-container">
          <div className="spinner"></div>
          <p>Processing your payment...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="success-page">
        <div className="error-container">
          <p className="error-message">{error}</p>
        </div>
      </div>
    );
  }

  return null;
}

export default Success;
