# AI Freelance Platform - Developer Setup Guide

This guide covers how to set up and run the complete AI Freelance Platform locally, including the Ollama local LLM instance, FastAPI backend, and Vite React frontend.

## Prerequisites

Before starting, ensure you have the following installed:

| Requirement | Version | Installation |
|------------|---------|--------------|
| Python | 3.10+ | [python.org](https://www.python.org/) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) |
| npm | 9+ | Comes with Node.js |
| Stripe CLI | Latest | [stripe.com/docs/cli](https://stripe.com/docs/cli) |
| Ollama | Latest | [ollama.ai](https://ollama.ai) |

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI Freelance Platform                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     │
│  │   Ollama     │────▶│   FastAPI    │────▶│    Vite     │     │
│  │  (P40 LLM)  │     │  Backend    │     │   Frontend   │     │
│  │  :11434     │     │   :8000     │     │   :5173     │     │
│  └──────────────┘     └──────────────┘     └──────────────┘     │
│         ▲                     │                     │              │
│         │                     ▼                     │              │
│         │              ┌──────────────┐             │              │
│         │              │   SQLite     │             │              │
│         │              │  tasks.db    │             │              │
│         │              └──────────────┘             │              │
│         │                                          │              │
│         └──────────────────────────────────────────┘              │
│                         Stripe Webhook                            │
│                  (forwarded via Stripe CLI)                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Step 1: Install Dependencies

### Python Dependencies

```bash
# Navigate to project root
cd /home/alexc/Projects/ai-freelance-platform

# Install Python dependencies
pip install -e .

# Or install from pyproject.toml
pip install fastapi uvicorn stripe openai e2b-code-interpreter python-dotenv pandas openpyxl PyPDF2 python-multipart chromadb sentence-transformers
```

### Node.js Dependencies

```bash
# Navigate to client portal
cd src/client_portal

# Install dependencies
npm install
```

---

## Step 2: Configure Environment Variables

Copy the example environment file and configure it:

```bash
# Copy example environment file
cp .env.example .env
```

Edit `.env` and configure the following:

```bash
# =============================================================================
# LLM SERVICE CONFIGURATION
# =============================================================================

# Cloud LLM Configuration (OpenAI) - Optional for local development
BASE_URL=https://api.openai.com/v1
API_KEY=your-openai-api-key-here
CLOUD_MODEL=gpt-4o-mini

# Local LLM Configuration (Ollama)
LOCAL_BASE_URL=http://localhost:11434/v1
LOCAL_API_KEY=not-needed
LOCAL_MODEL=llama3.2

# Set to "true" to use local models by default
USE_LOCAL_BY_DEFAULT=false

# Task-specific model configuration
TASK_USE_LOCAL_MAP={"basic_admin":true,"complex":false,"visualization":true,"document":true,"spreadsheet":true}

# =============================================================================
# OTHER API KEYS
# =============================================================================

# E2B Code Interpreter - Required for task execution
E2B_API_KEY=your-e2b-api-key-here

# Stripe Configuration
STRIPE_SECRET_KEY=sk_test_your_test_key
STRIPE_PUBLISHABLE_KEY=pk_test_your_publishable_key
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret
```

---

## Step 3: Start Ollama with P40 Parameters

The Nvidia P40 has 24GB VRAM. Below are recommended parameters for optimal performance:

### Option A: Using Environment Variables (Recommended)

Set these environment variables before starting Ollama:

```bash
# GPU Memory Optimization for P40 (24GB VRAM)
export OLLAMA_GPU_LAYERS=99
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_NUM_PARALLEL=4
export OLLAMA_MAX_LOADED_MODELS=1

# Context window optimization for P40
# The P40 can handle ~16K-32K context depending on model
export OLLAMA_CONTEXT_WINDOW=16384
export OLLAMA_NUKEM=1

# Start Ollama
ollama serve
```

### Option B: Pull a Specific Model with Optimized Settings

```bash
# Pull llama3.2 model (recommended for P40)
ollama pull llama3.2

# Verify model is available
ollama list
```

### Option C: Custom Model Configuration

For a custom model with P40-specific context window:

```bash
# Create a custom Modelfile for P40 optimization
cat > Modelfile << 'EOF'
FROM llama3.2
PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER num_ctx 16384
PARAMETER num_gpu 99
PARAMETER num_thread 8
PARAMETER repeat_penalty 1.1
EOF

# Create the model with custom settings
ollama create llama3.2-p40 -f Modelfile

# Verify it's available
ollama list
```

### Verify Ollama is Running

```bash
# Test Ollama API
curl http://localhost:11434/api/version

# Test a completion
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

---

## Step 4: Start the FastAPI Backend

```bash
# From project root
cd /home/alexc/Projects/ai-freelance-platform

# Start the backend server
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

The API will be available at:
- **Base URL**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/

### Backend Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health check |
| `/api/create-checkout-session` | POST | Create Stripe checkout |
| `/api/domains` | GET | Get available domains |
| `/api/calculate-price` | GET | Calculate task price |
| `/api/webhook` | POST | Stripe webhook handler |
| `/api/tasks/{task_id}` | GET | Get task by ID |
| `/api/session/{session_id}` | GET | Get task by session |
| `/api/client/history` | GET | Client task history |
| `/api/admin/metrics` | GET | Admin metrics |

---

## Step 5: Start the Vite React Frontend

```bash
# Navigate to client portal
cd /home/alexc/Projects/ai-freelance-platform/src/client_portal

# Start development server
npm run dev
```

The frontend will be available at: **http://localhost:5173**

### Frontend Commands

| Command | Description |
|---------|-------------|
| `npm run dev` | Start development server |
| `npm run build` | Build for production |
| `npm run preview` | Preview production build |
| `npm run lint` | Run ESLint |

---

## Step 6: Stripe Webhook Forwarding for Local Testing

To test Stripe webhooks locally, use the Stripe CLI to forward events to your local backend:

### Install Stripe CLI

**macOS (Homebrew):**
```bash
brew install stripe/stripe-cli/stripe
```

**Linux:**
```bash
# Download Stripe CLI
curl -s https://packages.stripe.com/stripe-signing-public keys | grep stripe-cli | head -1

# Or use the official installation script
stripe install
```

**Windows:**
Download from: https://github.com/stripe/stripe-cli/releases

### Login to Stripe

```bash
stripe login
```

### Forward Webhooks to Local Backend

```bash
# Forward all webhooks to localhost:8000/api/webhook
stripe listen --forward-to localhost:8000/api/webhook
```

### Forwarding with Webhook Secret

For production-like testing with signature verification:

```bash
# Listen and automatically forward to local backend
# The --forward-to flag handles the forwarding
stripe listen \
  --forward-to localhost:8000/api/webhook \
  --events checkout.session.completed,payment_intent.succeeded
```

**Important:** Copy the webhook signing secret that Stripe CLI outputs (starts with `whsec_`) and add it to your `.env` file:

```bash
# The CLI will output something like:
# > Ready! Your webhook signing secret is whsec_xxxxxxxxxxxxxxxxxxxx

# Add this to your .env:
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxxxxxxxxx
```

### Testing Webhooks

```bash
# Trigger a test webhook event
stripe trigger checkout.session.completed

# Or trigger a specific event type
stripe trigger payment_intent.succeeded
```

### Verify Webhook Forwarding

Check your backend logs to confirm webhooks are being received:

```bash
# You should see logs like:
# [2024-01-01 12:00:00] Received webhook: checkout.session.completed
# [2024-01-01 12:00:00] Task marked as PAID, processing started
```

---

## Quick Start Command Summary

Here's all the commands you need to run the full system:

```bash
# Terminal 1: Start Ollama
export OLLAMA_GPU_LAYERS=99
export OLLAMA_NUM_PARALLEL=4
export OLLAMA_CONTEXT_WINDOW=16384
ollama serve

# Terminal 2: Start FastAPI Backend
cd /home/alexc/Projects/ai-freelance-platform
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 3: Start Vite Frontend
cd /home/alexc/Projects/ai-freelance-platform/src/client_portal
npm run dev

# Terminal 4: Stripe Webhook Forwarding (for local testing)
stripe listen --forward-to localhost:8000/api/webhook
```

---

## Troubleshooting

### Ollama Issues

**Model won't load:**
```bash
# Check available GPU memory
nvidia-smi

# Reduce context window if OOM
export OLLAMA_CONTEXT_WINDOW=8192

# Restart Ollama
pkill ollama
ollama serve
```

**Slow inference:**
```bash
# Enable flash attention
export OLLAMA_FLASH_ATTENTION=1

# Increase parallel requests
export OLLAMA_NUM_PARALLEL=8
```

### Backend Issues

**Database error:**
```bash
# Ensure data directory exists
mkdir -p data

# Check database permissions
ls -la data/tasks.db
```

**Import errors:**
```bash
# Reinstall dependencies
pip install -e .
```

### Frontend Issues

**Port already in use:**
```bash
# Find and kill process on port 5173
lsof -i :5173
kill -9 <PID>

# Or run on different port
npm run dev -- --port 3000
```

**API not connecting:**
```bash
# Check backend is running
curl http://localhost:8000/

# Update frontend API URL if needed
# Edit src/client_portal/src/... (where API calls are made)
```

### Stripe Webhook Issues

**Signature verification failed:**
```bash
# Ensure STRIPE_WEBHOOK_SECRET matches the output from:
stripe listen

# The secret starts with "whsec_"
```

**Events not forwarding:**
```bash
# Check if Stripe CLI is running
stripe listen --verbose

# Verify local server is running
curl http://localhost:8000/api/webhook
```

---

## Production Deployment Notes

When deploying to production with the Nvidia P40:

1. **GPU Configuration**: Ensure CUDA drivers are installed and `nvidia-smi` works
2. **Ollama Service**: Consider running Ollama as a systemd service
3. **Environment Variables**: Use proper secret management (not .env files)
4. **SSL/TLS**: Use a reverse proxy (nginx) with SSL for HTTPS
5. **Stripe**: Configure proper webhook URLs in Stripe Dashboard

---

## Additional Resources

- [Ollama Documentation](https://github.com/ollama/ollama)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Vite Documentation](https://vitejs.dev/)
- [Stripe CLI Documentation](https://stripe.com/docs/cli)
- [Nvidia P40 Specifications](https://www.nvidia.com/en-us/data-center/tesla-p40/)
