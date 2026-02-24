import { useState } from 'react';
import './TaskSubmissionForm.css';

// Domain base rates (from API - could be fetched dynamically)
const DOMAINS = [
  { value: 'accounting', label: 'Accounting', basePrice: 100 },
  { value: 'legal', label: 'Legal', basePrice: 175 },
  { value: 'data_analysis', label: 'Data Analysis', basePrice: 150 },
];

// Complexity multipliers
const COMPLEXITY = [
  { value: 'simple', label: 'Simple', multiplier: 1.0 },
  { value: 'medium', label: 'Medium', multiplier: 1.5 },
  { value: 'complex', label: 'Complex', multiplier: 2.0 },
];

// Urgency multipliers
const URGENCY = [
  { value: 'standard', label: 'Standard (3-5 days)', multiplier: 1.0 },
  { value: 'rush', label: 'Rush (1-2 days)', multiplier: 1.25 },
  { value: 'urgent', label: 'Urgent (same day)', multiplier: 1.5 },
];

// Calculate price using the formula: Base Rate × Complexity × Urgency
const calculatePrice = (domain, complexity, urgency) => {
  const domainData = DOMAINS.find(d => d.value === domain);
  const complexityData = COMPLEXITY.find(c => c.value === complexity);
  const urgencyData = URGENCY.find(u => u.value === urgency);
  
  if (!domainData || !complexityData || !urgencyData) return null;
  
  return Math.round(domainData.basePrice * complexityData.multiplier * urgencyData.multiplier);
};

const API_BASE_URL = 'http://localhost:8000';

function TaskSubmissionForm() {
  const [formData, setFormData] = useState({
    domain: '',
    title: '',
    description: '',
    complexity: 'medium',
    urgency: 'standard',
    clientEmail: '',
    file: null,
  });
  const [estimatedPrice, setEstimatedPrice] = useState(null);
  const [discountInfo, setDiscountInfo] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Fetch discount info when client email is entered
  const fetchDiscountInfo = async (email) => {
    if (!email || !email.includes('@')) {
      setDiscountInfo(null);
      return;
    }
    
    try {
      const response = await fetch(`${API_BASE_URL}/api/client/discount-info?email=${encodeURIComponent(email)}`);
      if (response.ok) {
        const data = await response.json();
        setDiscountInfo(data);
      }
    } catch (err) {
      console.error('Failed to fetch discount info:', err);
      setDiscountInfo(null);
    }
  };

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
    
    // Fetch discount info when client email changes
    if (name === 'clientEmail') {
      fetchDiscountInfo(value);
    }
    
    // Recalculate price when domain, complexity, or urgency changes
    if (name === 'domain' || name === 'complexity' || name === 'urgency') {
      const domain = name === 'domain' ? value : formData.domain;
      const complexity = name === 'complexity' ? value : formData.complexity;
      const urgency = name === 'urgency' ? value : formData.urgency;
      
      const price = calculatePrice(domain, complexity, urgency);
      setEstimatedPrice(price);
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
        complexity: formData.complexity,
        urgency: formData.urgency,
        client_email: formData.clientEmail || null,
      };

      // Include the raw CSV string if a file was uploaded
      if (formData.file) {
        payload.csvContent = formData.file;
      }

      const response = await fetch(`${API_BASE_URL}/api/create-checkout-session`, {
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
                {domain.label} (Base: ${domain.basePrice})
              </option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label htmlFor="complexity">Complexity</label>
          <select
            id="complexity"
            name="complexity"
            value={formData.complexity}
            onChange={handleChange}
            required
          >
            {COMPLEXITY.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label} (×{item.multiplier})
              </option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label htmlFor="urgency">Urgency</label>
          <select
            id="urgency"
            name="urgency"
            value={formData.urgency}
            onChange={handleChange}
            required
          >
            {URGENCY.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label} (×{item.multiplier})
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
          <label htmlFor="clientEmail">Your Email (for order history & loyalty discounts)</label>
          <input
            type="email"
            id="clientEmail"
            name="clientEmail"
            value={formData.clientEmail}
            onChange={handleChange}
            placeholder="your@email.com"
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

        {/* Discount Info Display */}
        {discountInfo && discountInfo.current_discount > 0 && (
          <div className="discount-badge">
            🎉 Welcome back! You qualify for a <strong>{discountInfo.current_discount * 100}% discount</strong>!
          </div>
        )}

        {estimatedPrice !== null && (
          <div className="price-estimate">
            <strong>Estimated Price: ${estimatedPrice}</strong>
            <br />
            <small style={{ fontWeight: 'normal', opacity: 0.8 }}>
              Base × Complexity × Urgency
            </small>
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
