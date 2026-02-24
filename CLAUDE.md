# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ArbitrageAI is an AI-powered freelance platform that processes client tasks using multiple LLM models and secure sandbox execution. The system handles data visualization, document processing, and spreadsheet analysis through a multi-agent architecture.

## Architecture

### Core Components
- **FastAPI Backend** (`src/api/main.py`): REST API with Stripe integration, task management, and webhook handling
- **Vite React Frontend** (`src/client_portal/`): User interface for task submission and tracking
- **Multi-LLM Service** (`src/llm_service.py`): Chooses between OpenAI cloud models and local Ollama models
- **Docker Sandbox** (`src/agent_execution/docker_sandbox.py`): Secure code execution environment
- **Experience Vector Database** (`src/experience_vector_db.py`): RAG system for few-shot learning
- **Telemetry & Observability** (`src/utils/telemetry.py`): OpenTelemetry integration with Phoenix dashboard

### Data Flow
1. Client submits task via frontend
2. Payment processed through Stripe webhook
3. Task routed to appropriate LLM model
4. Code executed in Docker sandbox
5. Results reviewed by ArtifactReviewer agent
6. Experience stored in vector database for future tasks

## Development Commands

### Quick Start with Just (Recommended - February 2026)
```bash
# Install just command runner (once)
brew install just   # or: curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash

# Start all services with one command
just start

# Other useful commands
just setup        # First-time setup (dependencies + Docker image)
just status       # Check which services are running
just stop         # Stop all services
just backend      # Start only backend
just frontend     # Start only frontend
just ollama       # Start only Ollama with P40 optimizations
just test        # Run tests
just lint        # Run linter
just format      # Format code
just docs        # Open API docs in browser
```

### Backend Development
>>>>>>> ++++++ REPLACE

```bash
# Install Python dependencies
pip install -e .

# Start FastAPI server
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# Run tests
pytest tests/

# Run single test
pytest tests/test_api_endpoints.py::test_create_checkout_session
```

### Frontend Development
```bash
# Navigate to client portal
cd src/client_portal

# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build
```

### Docker Setup
```bash
# Build sandbox base image
docker build -t ai-sandbox-base -f Dockerfile.sandbox .

# Add user to docker group (log out and back in after)
sudo usermod -aG docker $USER
```

### Ollama Setup (Local LLM)
```bash
# Start Ollama with P40 optimization
export OLLAMA_GPU_LAYERS=99
export OLLAMA_NUM_PARALLEL=4
export OLLAMA_CONTEXT_WINDOW=16384
ollama serve
```

## Code Structure

### Source Organization
- `src/api/`: FastAPI endpoints and database models
- `src/agent_execution/`: Task execution and sandbox management
- `src/llm_service.py`: Multi-LLM configuration and routing
- `src/utils/`: Utilities for logging, telemetry, and notifications
- `src/client_portal/`: React frontend with Vite

### Key Files
- `src/api/main.py`: Main FastAPI application with all endpoints
- `src/agent_execution/executor.py`: Task execution logic with retry mechanisms
- `src/api/models.py`: SQLAlchemy models for tasks, clients, and reviews
- `src/client_portal/src/App.jsx`: React application entry point

## Testing Strategy

### Test Types
- **API Tests**: Test FastAPI endpoints and Stripe integration
- **Unit Tests**: Test individual components and utilities
- **Integration Tests**: Test end-to-end workflows

### Test Commands
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_api_endpoints.py

# Run with verbose output
pytest -v
```

## Database Schema

### Core Tables
- **tasks**: Main task table with status tracking and execution logs
- **client_profiles**: Client preference memory for personalized results
- **bids**: Bid tracking for arena competitions
- **arena_competitions**: Multi-agent task competitions

### Key Fields
- `task.status`: PENDING, PAID, PLANNING, PROCESSING, REVIEW_REQUIRED, COMPLETED, FAILED
- `task.plan_status`: PENDING, GENERATING, APPROVED, REJECTED
- `task.review_status`: PENDING, IN_REVIEW, RESOLVED, REJECTED

## Multi-LLM Configuration

### Model Selection
- **Local Models**: Ollama with llama3.2 (default for cost savings)
- **Cloud Models**: OpenAI GPT-4o-mini for complex tasks
- **Task-Specific Routing**: Different models for different task types

### Environment Variables
```bash
# Local LLM Configuration
LOCAL_BASE_URL=http://localhost:11434/v1
LOCAL_MODEL=llama3.2
USE_LOCAL_BY_DEFAULT=true

# Cloud LLM Configuration
BASE_URL=https://api.openai.com/v1
API_KEY=your-api-key
CLOUD_MODEL=gpt-4o-mini
```

## Security Considerations

### Docker Sandbox
- Uses isolated Docker containers for code execution
- Base image: `ai-sandbox-base` with restricted permissions
- Timeout: 120 seconds per task execution
- Resource limits to prevent abuse

### Stripe Integration
- Webhook verification with signing secrets
- Secure payment processing
- Token-based delivery links

## Observability

### Telemetry Stack
- **OpenTelemetry**: Distributed tracing
- **Arize Phoenix**: Real-time observability dashboard
- **Traceloop**: Auto-instrumentation for LLM calls

### Monitoring Commands
```bash
# Start Phoenix dashboard (development only)
phx serve

# Check traces
curl http://localhost:6006/v1/traces
```

## Development Workflow

### Feature Development
1. Create feature branch from main
2. Add tests for new functionality
3. Implement feature following existing patterns
4. Update documentation if needed
5. Create pull request for review

### Bug Fixes
1. Identify root cause in logs
2. Add failing test case if applicable
3. Fix issue following existing patterns
4. Verify fix with regression tests
5. Update documentation if needed

## Common Patterns

### Task Processing Flow
1. Payment confirmed via Stripe webhook
2. Task status: PENDING → PAID
3. Plan generated (PLANNING → APPROVED)
4. Code executed in sandbox (PROCESSING)
5. Results reviewed (REVIEW_REQUIRED → COMPLETED)

### Error Handling
- Retry mechanism: Up to 3 attempts for code execution
- Escalation: Human review for failed high-value tasks
- Comprehensive logging: All steps tracked in database

## Configuration Files

### Key Configuration
- `pyproject.toml`: Python dependencies and project metadata
- `src/client_portal/package.json`: Frontend dependencies and scripts
- `.env.example`: Environment variables template
- `Dockerfile.sandbox`: Docker sandbox base image

## Performance Considerations

### Local LLM Optimization (P40 GPU)
- Context window: 16384 tokens
- GPU layers: 99
- Parallel requests: 4
- Flash attention: Enabled

### Database Optimization
- SQLite with proper indexing
- JSON fields for flexible data storage
- Connection pooling for concurrent requests

## Deployment Notes

### Production Requirements
- GPU-enabled server (Nvidia P40 recommended)
- Docker and Ollama installed
- SSL/TLS for secure communication
- Proper environment variable management
- Stripe webhook endpoint configured