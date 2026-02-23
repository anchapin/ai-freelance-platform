"""
FastAPI backend for the AI Freelance Platform.
Provides endpoints for creating checkout sessions and processing task submissions.
"""
import uuid
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import stripe
from typing import Optional

# Initialize FastAPI app
app = FastAPI(title="AI Freelance Platform API")

# Configure Stripe (use test key for development)
# In production, use environment variable: os.environ.get('STRIPE_SECRET_KEY')
stripe.api_key = "sk_test_placeholder"

# Domain pricing configuration
DOMAIN_PRICES = {
    "accounting": 150,
    "legal": 250,
    "data_analysis": 200,
}


class TaskSubmission(BaseModel):
    """Model for task submission data."""
    domain: str
    title: str
    description: str


class CheckoutResponse(BaseModel):
    """Model for checkout session response."""
    session_id: str
    amount: int
    domain: str
    title: str


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "AI Freelance Platform API is running"}


@app.post("/api/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(task: TaskSubmission):
    """
    Create a Stripe checkout session based on task submission.
    
    Calculates price based on domain and returns a mock Stripe checkout session.
    """
    # Validate domain
    if task.domain not in DOMAIN_PRICES:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid domain. Must be one of: {', '.join(DOMAIN_PRICES.keys())}"
        )
    
    # Get price for domain
    amount = DOMAIN_PRICES[task.domain]
    
    try:
        # Create Stripe checkout session
        # In production, this would create a real Stripe session
        # For now, we create a mock session ID for demonstration
        session_id = f"cs_test_{uuid.uuid4().hex[:24]}"
        
        # In a real implementation, you would create a Stripe session like this:
        """
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'{task.domain.title()} Task: {task.title}',
                        'description': task.description[:500],
                    },
                    'unit_amount': amount * 100,  # Stripe uses cents
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://your-domain.com/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url='https://your-domain.com/cancel',
            metadata={
                'domain': task.domain,
                'title': task.title,
            }
        )
        session_id = checkout_session.id
        """
        
        return CheckoutResponse(
            session_id=session_id,
            amount=amount,
            domain=task.domain,
            title=task.title
        )
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=500, detail=f"Stripe error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@app.get("/api/domains")
async def get_domains():
    """Get available domains and their prices."""
    return {
        "domains": [
            {"value": domain, "label": domain.replace("_", " ").title(), "price": price}
            for domain, price in DOMAIN_PRICES.items()
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
