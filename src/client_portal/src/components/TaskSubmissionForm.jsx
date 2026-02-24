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
    file: null,
  });
  const [estimatedPrice, setEstimatedPrice] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (e) => {
    const { name, value, files } = e.target;
    
    if (name === 'file' && files.length > 0) {
      const file = files[0];
      const reader = new FileReader();
      reader.onload = (event) => {
        const csvContent = event.target.result;
        setFormData((prev) => ({ ...prev, file: csvContent }));
      };
      reader.readAsText(file);
    } else {
      setFormData((prev) => ({ ...prev, [name]: value }));
    }
    
    if (name === 'domain') {
      const selectedDomain = DOMAINS.find((d) => d.value === value);
      setEstimatedPrice(selectedDomain ? selectedDomain.price : null);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const payload = {
        domain: formData.domain,
        title: formData.title,
        description: formData.description,
      };

      // Include the raw CSV string if a file was uploaded
      if (formData.file) {
        payload.csvContent = formData.file;
      }

      const response = await fetch('http://localhost:8000/api/create-checkout-session', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error('Failed to create checkout session');
      }

      const data = await response.json();
      
      // Redirect to Stripe Checkout
      window.location.href = data.url;
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

        <div className="form-group">
          <label htmlFor="file">Attachment (CSV)</label>
          <input
            type="file"
            id="file"
            name="file"
            accept=".csv"
            onChange={handleChange}
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
