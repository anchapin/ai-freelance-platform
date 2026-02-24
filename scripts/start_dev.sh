#!/bin/bash

# ArbitrageAI - Development Startup Script
# This script starts all required services for local development

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Project root directory
PROJECT_ROOT="/home/alexc/Projects/ArbitrageAI"

# Default ports
DEFAULT_BACKEND_PORT=8000
DEFAULT_FRONTEND_PORT=5173

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}           ArbitrageAI - Dev Startup    ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Function to check if a command exists
check_command() {
    if command -v "$1" &> /dev/null; then
        echo -e "${GREEN}✓${NC} $1 is installed"
        return 0
    else
        echo -e "${RED}✗${NC} $1 is not installed"
        return 1
    fi
}

# Function to check if a port is in use
check_port() {
    local port=$1
    if ss -tuln 2>/dev/null | grep -q ":${port} " || lsof -i :$port &>/dev/null; then
        return 0  # Port is in use
    fi
    return 1  # Port is free
}

# Function to find an available port starting from a given port
find_available_port() {
    local port=$1
    while check_port $port; do
        echo -e "${YELLOW}Port $port is in use, trying next port...${NC}"
        ((port++))
    done
    echo $port
}

# Check required commands
echo -e "${YELLOW}Checking required commands...${NC}"
check_command "ollama" || echo -e "${YELLOW}  Note: Ollama not found. Install from https://ollama.ai${NC}"
check_command "uvicorn" || echo -e "${YELLOW}  Note: Uvicorn not found. Install with: pip install uvicorn${NC}"
check_command "stripe" || echo -e "${YELLOW}  Note: Stripe CLI not found. Install from https://stripe.com/docs/stripe-cli${NC}"
echo ""

# Check for existing services and handle port conflicts
echo -e "${YELLOW}Checking for existing services...${NC}"

# Check FastAPI port
if check_port $DEFAULT_BACKEND_PORT; then
    echo -e "${YELLOW}! Port $DEFAULT_BACKEND_PORT is already in use${NC}"
    echo -e "${YELLOW}  Checking for existing uvicorn processes...${NC}"
    EXISTING_UVICORN=$(pgrep -f "uvicorn.*src.api.main" || true)
    if [ -n "$EXISTING_UVICORN" ]; then
        echo -e "${CYAN}  Found existing uvicorn process(es): $EXISTING_UVICORN${NC}"
        echo -e "${YELLOW}  Will use existing backend on port $DEFAULT_BACKEND_PORT${NC}"
        BACKEND_ALREADY_RUNNING=true
    else
        # Find alternative port
        BACKEND_PORT=$(find_available_port $((DEFAULT_BACKEND_PORT + 1)))
        echo -e "${CYAN}  Will use alternative port: $BACKEND_PORT${NC}"
        BACKEND_ALREADY_RUNNING=false
    fi
else
    BACKEND_PORT=$DEFAULT_BACKEND_PORT
    BACKEND_ALREADY_RUNNING=false
fi

# Check Vite ports (5173, 5174, 5175 are common)
FRONTEND_PORT=""
for port in 5173 5174 5175 5176 5177; do
    if ! check_port $port; then
        FRONTEND_PORT=$port
        break
    fi
done
if [ -z "$FRONTEND_PORT" ]; then
    FRONTEND_PORT=$(find_available_port 5178)
fi

echo ""

# Export Ollama environment variables
export OLLAMA_GPU_LAYERS=99
export OLLAMA_NUM_PARALLEL=4
export OLLAMA_CONTEXT_WINDOW=16384

# Start services
echo -e "${YELLOW}Starting all services...${NC}"
echo ""

# Terminal 1: Ollama
echo -e "${BLUE}--- Terminal 1: Ollama ---${NC}"
echo "Command: ollama serve"
echo "Environment variables:"
echo "  OLLAMA_GPU_LAYERS=99"
echo "  OLLAMA_NUM_PARALLEL=4"
echo "  OLLAMA_CONTEXT_WINDOW=16384"
echo ""
echo -e "${YELLOW}To start manually in Terminal 1:${NC}"
echo "  export OLLAMA_GPU_LAYERS=99"
echo "  export OLLAMA_NUM_PARALLEL=4"
echo "  export OLLAMA_CONTEXT_WINDOW=16384"
echo "  ollama serve"
echo ""

# Terminal 2: FastAPI Backend
echo -e "${BLUE}--- Terminal 2: FastAPI Backend ---${NC}"
echo "Starting FastAPI on http://localhost:$BACKEND_PORT"

if [ "$BACKEND_ALREADY_RUNNING" = true ]; then
    echo -e "${GREEN}✓${NC} Using existing FastAPI Backend (port $BACKEND_PORT)"
else
    cd "$PROJECT_ROOT"
    # Start uvicorn and capture the PID
    uvicorn src.api.main:app --host 0.0.0.0 --port $BACKEND_PORT --reload &
    BACKEND_PID=$!
    echo -e "${GREEN}✓${NC} FastAPI Backend started (PID: $BACKEND_PID)"
    
    # Wait for backend to start
    echo -e "${YELLOW}Waiting for backend to start...${NC}"
    for i in {1..10}; do
        if curl -s http://localhost:$BACKEND_PORT/docs &>/dev/null; then
            echo -e "${GREEN}Backend is ready!${NC}"
            break
        fi
        sleep 1
    done
fi
echo ""

# Terminal 3: Vite Frontend
echo -e "${BLUE}--- Terminal 3: Vite Frontend ---${NC}"
echo "Starting Vite dev server on http://localhost:$FRONTEND_PORT"

# Check if there's an existing Vite process we can use
EXISTING_VITE_PORT=""
for port in 5173 5174 5175 5176 5177; do
    if check_port $port; then
        # This port is in use, check if it's Vite
        if ss -tuln 2>/dev/null | grep -q ":${port} " && lsof -i :$port 2>/dev/null | grep -q node; then
            EXISTING_VITE_PORT=$port
            break
        fi
    fi
done

if [ -n "$EXISTING_VITE_PORT" ]; then
    echo -e "${GREEN}✓${NC} Using existing Vite Frontend on port $EXISTING_VITE_PORT"
    FRONTEND_PORT=$EXISTING_VITE_PORT
else
    cd "$PROJECT_ROOT/src/client_portal"
    # Set the port explicitly to avoid Vite's port finding
    VITE_PORT=$FRONTEND_PORT npm run dev &
    FRONTEND_PID=$!
    echo -e "${GREEN}✓${NC} Vite Frontend started (PID: $FRONTEND_PID)"
    
    # Wait for frontend to start
    echo -e "${YELLOW}Waiting for frontend to start...${NC}"
    for i in {1..15}; do
        if curl -s http://localhost:$FRONTEND_PORT &>/dev/null; then
            echo -e "${GREEN}Frontend is ready!${NC}"
            break
        fi
        sleep 1
    done
fi
echo ""

# Terminal 4: Stripe Webhook
echo -e "${BLUE}--- Terminal 4: Stripe Webhook ---${NC}"
echo -e "${YELLOW}Note: Stripe webhook forwarding requires Stripe CLI${NC}"
echo "Command: stripe listen --forward-to localhost:$BACKEND_PORT/api/webhook"
echo ""

# Summary
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  All services started!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Service URLs:"
echo "  - Frontend:    http://localhost:$FRONTEND_PORT"
echo "  - Backend:     http://localhost:$BACKEND_PORT"
echo "  - API Docs:    http://localhost:$BACKEND_PORT/docs"
echo "  - Stripe CLI:  https://stripe.com/docs/stripe-cli"
echo ""
echo -e "${YELLOW}To stop all services, run:${NC}"
echo "  pkill -f 'uvicorn.*src.api.main' && pkill -f 'vite' && pkill -f 'ollama'"
echo ""
