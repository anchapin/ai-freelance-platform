# ArbitrageAI - Justfile
# Modern task runner for quick project commands
# Install just: https://just.systems/install.sh

# Default recipe - shows help
default:
    @just --list

# ===========================================
# QUICK START
# ===========================================

# Start all services (Ollama + Backend + Frontend)
start:
    #!/usr/bin/env bash
    set -e
    echo "Starting all ArbitrageAI services..."
    echo ""
    
    # Ensure logs directory exists
    mkdir -p /home/alexc/Projects/ArbitrageAI/logs
    
    # Start Ollama in background
    echo "Starting Ollama..."
    export OLLAMA_GPU_LAYERS=99
    export OLLAMA_NUM_PARALLEL=4
    export OLLAMA_CONTEXT_WINDOW=16384
    nohup ollama serve > /home/alexc/Projects/ArbitrageAI/logs/ollama.log 2>&1 &
    echo "Ollama started in background (check logs/ollama.log)"
    
    # Start Backend in background
    cd /home/alexc/Projects/ArbitrageAI
    echo "Starting FastAPI backend..."
    nohup uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload > /home/alexc/Projects/ArbitrageAI/logs/backend.log 2>&1 &
    
    # Wait for backend to start
    sleep 3
    
    # Start Frontend in background
    cd /home/alexc/Projects/ArbitrageAI/src/client_portal
    echo "Starting Vite frontend..."
    nohup npm run dev > /home/alexc/Projects/ArbitrageAI/logs/frontend.log 2>&1 &
    
    echo ""
    echo "=========================================="
    echo "  All services started!"
    echo "=========================================="
    echo "  Frontend:  http://localhost:5173"
    echo "  Backend:   http://localhost:8000"
    echo "  API Docs:  http://localhost:8000/docs"
    echo ""

# Alias for start
serve: start

# ===========================================
# INDIVIDUAL SERVICES
# ===========================================

# Start FastAPI backend only
backend:
    #!/usr/bin/env bash
    set -e
    cd /home/alexc/Projects/ArbitrageAI
    mkdir -p logs
    echo "Starting FastAPI backend on port 8000..."
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# Start Vite frontend only
frontend:
    #!/usr/bin/env bash
    set -e
    cd /home/alexc/Projects/ArbitrageAI/src/client_portal
    echo "Starting Vite frontend on port 5173..."
    npm run dev

# Start Ollama with P40 optimizations
ollama:
    #!/usr/bin/env bash
    set -e
    cd /home/alexc/Projects/ArbitrageAI
    mkdir -p logs
    export OLLAMA_GPU_LAYERS=99
    export OLLAMA_NUM_PARALLEL=4
    export OLLAMA_CONTEXT_WINDOW=16384
    export OLLAMA_FLASH_ATTENTION=1
    echo "Starting Ollama with P40 optimizations..."
    echo "  GPU_LAYERS: $OLLAMA_GPU_LAYERS"
    echo "  NUM_PARALLEL: $OLLAMA_NUM_PARALLEL"
    echo "  CONTEXT_WINDOW: $OLLAMA_CONTEXT_WINDOW"
    nohup ollama serve > logs/ollama.log 2>&1 &
    echo "Ollama started (logs: logs/ollama.log)"

# ===========================================
# INSTALLATION & SETUP
# ===========================================

# Install all dependencies (Python + Node.js)
install:
    #!/usr/bin/env bash
    set -e
    cd /home/alexc/Projects/ArbitrageAI
    echo "Installing Python dependencies..."
    pip install -e .
    echo ""
    echo "Installing Node.js dependencies..."
    cd /home/alexc/Projects/ArbitrageAI/src/client_portal
    npm install

# Full first-time setup (dependencies + Docker image)
setup: install
    #!/usr/bin/env bash
    set -e
    cd /home/alexc/Projects/ArbitrageAI
    echo "Building Docker sandbox image..."
    docker build -t ai-sandbox-base -f Dockerfile.sandbox .
    echo ""
    echo "Setup complete! Run 'just start' to begin."

# ===========================================
# SERVICE MANAGEMENT
# ===========================================

# Stop all running services
stop:
    #!/usr/bin/env bash
    echo "Stopping ArbitrageAI services..."
    pkill -f 'uvicorn.*src.api.main' && echo "✓ Stopped backend" || echo "- Backend not running"
    pkill -f 'vite' && echo "✓ Stopped frontend" || echo "- Frontend not running"
    echo "Services stopped."

# Show status of all services
status:
    #!/usr/bin/env bash
    echo "Checking ArbitrageAI services..."
    echo ""
    # Check Ollama
    if curl -s http://localhost:11434/api/version > /dev/null 2>&1; then
        echo "✓ Ollama: running"
    else
        echo "✗ Ollama: not running"
    fi
    # Check Backend
    if curl -s http://localhost:8000/ > /dev/null 2>&1; then
        echo "✓ Backend: running (http://localhost:8000)"
    else
        echo "✗ Backend: not running"
    fi
    # Check Frontend
    if curl -s http://localhost:5173/ > /dev/null 2>&1; then
        echo "✓ Frontend: running (http://localhost:5173)"
    else
        echo "✗ Frontend: not running"
    fi
    echo ""

# Show logs for a service
logs service:
    #!/usr/bin/env bash
    case {{service}} in
        ollama)
            tail -f /home/alexc/Projects/ArbitrageAI/logs/ollama.log
            ;;
        backend)
            tail -f /home/alexc/Projects/ArbitrageAI/logs/backend.log
            ;;
        frontend)
            tail -f /home/alexc/Projects/ArbitrageAI/logs/frontend.log
            ;;
        *)
            echo "Available services: ollama, backend, frontend"
            ;;
    esac

# ===========================================
# DEVELOPMENT COMMANDS
# ===========================================

# Run tests
test:
    #!/usr/bin/env bash
    set -e
    cd /home/alexc/Projects/ArbitrageAI
    pytest tests/ -v

# Run linter
lint:
    #!/usr/bin/env bash
    set -e
    cd /home/alexc/Projects/ArbitrageAI
    ruff check src/

# Format code
format:
    #!/usr/bin/env bash
    set -e
    cd /home/alexc/Projects/ArbitrageAI
    ruff format src/

# Open API docs in browser
docs:
    #!/usr/bin/env bash
    if command -v xdg-open > /dev/null; then
        xdg-open http://localhost:8000/docs
    elif command -v open > /dev/null; then
        open http://localhost:8000/docs
    else
        echo "Open http://localhost:8000/docs in your browser"
    fi
