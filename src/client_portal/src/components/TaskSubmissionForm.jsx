import { useState } from 'react';
import './TaskSubmissionForm.css';

const DOMAINS = [
  { value: 'accounting', label: 'Accounting', price: 150 },
  { value: 'legal', label: 'Legal', price: 250 },
  { value: 'data_analysis', label: 'Data Analysis', price: 200 },
];

function TaskSubmissionForm() {
  const [formData, setFormData] = useState({
    domain: '',
    title: '',
    description: '',
  });
  const [estimatedPrice, setEstimatedPrice] = useState(null);
  const [sessionId, setSessionId] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    
    if (name === 'domain') {
      const selectedDomain = DOMAINS.find((d) => d.value === value);
      setEstimatedPrice(selectedDomain ? selectedDomain.price : null);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSessionId(null);

    try {
      const response = await fetch('http://localhost:8000/api/create-checkout-session', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          domain: formData.domain,
          title: formData.title,
          description: formData.description,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to create checkout session');
      }

      const data = await response.json();
      setSessionId(data.session_id);
      
      // Redirect to Stripe Checkout (mock - in production would use Stripe.js)
      alert(`Stripe Checkout Session Created: ${data.session_id}\nAmount: $${data.amount}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="task-submission-form">
      <h2>Submit a Task</h2>
      <form onSubmit={handleSubmit}>
        <div className="form-group">
          <label htmlFor="domain">Domain</label>
          <select
            id="domain"
            name="domain"
            value={formData.domain}
            onChange={handleChange}
            required
          >
            <option value="">Select a domain</option>
            {DOMAINS.map((domain) => (
              <option key={domain.value} value={domain.value}>
                {domain.label}
              </option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label htmlFor="title">Task Title</label>
          <input
            type="text"
            id="title"
            name="title"
            value={formData.title}
            onChange={handleChange}
            required
            placeholder="Enter task title"
          />
        </div>

        <div className="form-group">
          <label htmlFor="description">Description</label>
          <textarea
            id="description"
            name="description"
            value={formData.description}
            onChange={handleChange}
            required
            placeholder="Describe your task"
            rows={5}
          />
        </div>

        {estimatedPrice !== null && (
          <div className="price-estimate">
            <strong>Estimated Price: ${estimatedPrice}</strong>
          </div>
        )}

        {error && <div className="error-message">{error}</div>}

        <button type="submit" disabled={loading || !estimatedPrice}>
          {loading ? 'Processing...' : 'Proceed to Payment'}
        </button>
      </form>
    </div>
  );
}

export default TaskSubmissionForm;
