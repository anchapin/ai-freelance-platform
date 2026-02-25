# Issue #28: Quick Reference - URL Configuration

## Overview
All hardcoded external service URLs have been moved to environment variables.

## Environment Variables

| Variable | Default | Used By | Purpose |
|----------|---------|---------|---------|
| `OLLAMA_URL` | `http://localhost:11434/v1` | LLM Service | Local model inference endpoint |
| `TRACELOOP_URL` | `http://localhost:6006/v1/traces` | Telemetry | OpenTelemetry trace collector |
| `TELEGRAM_API_URL` | `https://api.telegram.org` | Notifications | Telegram Bot API endpoint |

## Usage Examples

### In Application Code

```python
# LLM Service
from src.llm_service import ModelConfig
config = ModelConfig()
# Automatically uses OLLAMA_URL env var or default

# Telemetry
from src.utils.telemetry import init_observability
init_observability()
# Automatically uses TRACELOOP_URL env var or default

# Notifications
from src.utils.notifications import TelegramNotifier
notifier = TelegramNotifier()
# Automatically uses TELEGRAM_API_URL env var or default
```

### In Configuration

```python
# Get current URLs
from src.config import (
    get_ollama_url,
    get_traceloop_url,
    get_telegram_api_url,
    validate_urls
)

# Get individual URLs
ollama = get_ollama_url()
traceloop = get_traceloop_url()
telegram = get_telegram_api_url()

# Validate all URLs are properly configured
validate_urls()  # Raises ValueError if misconfigured
```

## Development Setup

```bash
# 1. Copy default configuration
cp .env.example .env

# 2. Override URLs if needed (optional for local development)
# Edit .env:
# OLLAMA_URL=http://localhost:11434/v1
# TRACELOOP_URL=http://localhost:6006/v1/traces
# TELEGRAM_API_URL=https://api.telegram.org

# 3. Run tests to verify configuration
pytest tests/test_config.py -v
```

## Production Deployment

### Example: AWS EC2 with Remote Services

```bash
# .env for production
OLLAMA_URL=https://ollama.prod.example.com/v1
TRACELOOP_URL=https://observability.prod.example.com/v1/traces
TELEGRAM_API_URL=https://api.telegram.org
```

### Example: Docker Compose with Service Discovery

```bash
# .env for Docker Compose
OLLAMA_URL=http://ollama:11434/v1
TRACELOOP_URL=http://phoenix:6006/v1/traces
TELEGRAM_API_URL=https://api.telegram.org
```

### Example: Kubernetes with Service Mesh

```bash
# .env for K8s
OLLAMA_URL=http://ollama.ml-stack.svc.cluster.local:11434/v1
TRACELOOP_URL=http://phoenix.observability.svc.cluster.local:6006/v1/traces
TELEGRAM_API_URL=https://api.telegram.org
```

## Validation

### Check Configuration

```python
from src.config import validate_urls

try:
    validate_urls()
    print("✓ All URLs properly configured")
except ValueError as e:
    print(f"✗ Configuration error: {e}")
```

### Check URL Availability

```python
import httpx

async def check_urls():
    async with httpx.AsyncClient() as client:
        # Check Ollama
        response = await client.get(f"{get_ollama_url()}/models")
        print(f"Ollama: {response.status_code}")
        
        # Check Traceloop
        response = await client.get(get_traceloop_url())
        print(f"Traceloop: {response.status_code}")
```

## Testing

Run configuration tests:

```bash
# Run all URL configuration tests
pytest tests/test_config.py -v

# Run specific test class
pytest tests/test_config.py::TestOllamaUrlConfiguration -v

# Run with coverage
pytest tests/test_config.py --cov=src.config --cov-report=html
```

## Migration Guide

### If You Have Old Hardcoded URLs

Remove these patterns from your .env:
```bash
# OLD (no longer used)
BASE_URL=http://localhost:11434/v1  # For Ollama
```

Replace with:
```bash
# NEW
OLLAMA_URL=http://localhost:11434/v1
```

### If You Have Custom Service Names

```bash
# Before (custom Ollama instance)
# You had to modify code

# After (using environment variables)
OLLAMA_URL=http://my-custom-ollama:11434/v1
# No code changes needed!
```

## Troubleshooting

### "OLLAMA_URL is not configured"

```bash
# Solution: Check .env file
grep OLLAMA_URL .env

# Or set it:
export OLLAMA_URL=http://localhost:11434/v1
```

### "Invalid URL format"

```bash
# Invalid: Missing protocol
OLLAMA_URL=localhost:11434/v1  # ✗

# Valid: Must have http:// or https://
OLLAMA_URL=http://localhost:11434/v1  # ✓
```

### Connection Refused

```bash
# Check service is running
curl http://localhost:11434/v1/models  # Ollama
curl http://localhost:6006/v1/traces    # Traceloop
curl https://api.telegram.org/           # Telegram

# If not running:
docker-compose up -d ollama  # Start Ollama
```

## Files Modified

1. **src/config.py** - URL configuration functions
2. **src/llm_service.py** - Uses get_ollama_url()
3. **src/utils/telemetry.py** - Uses get_traceloop_url()
4. **src/utils/notifications.py** - Uses get_telegram_api_url()
5. **.env.example** - Documents all URL variables
6. **tests/test_config.py** - Comprehensive test suite

## Related Documentation

- [ISSUE_28_CONFIGURATION_URLS.md](ISSUE_28_CONFIGURATION_URLS.md) - Full implementation details
- [.env.example](.env.example) - Configuration template
- [src/config.py](src/config.py) - Implementation

---

**Last Updated:** 2026-02-25  
**Status:** ✅ Complete (Issue #28)
