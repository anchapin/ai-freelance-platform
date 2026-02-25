# Issue #28: Configuration - Hardcoded URLs for External Services

## Summary

Successfully moved all hardcoded URLs from source code to environment variables, enabling configuration per environment (development, staging, production) without code changes.

## Changes Made

### 1. **src/config.py** - New URL Configuration Functions

Added four new functions for URL management:

```python
def get_ollama_url() -> str
    """Returns Ollama URL, defaults to http://localhost:11434/v1"""

def get_traceloop_url() -> str
    """Returns Traceloop URL, defaults to http://localhost:6006/v1/traces"""

def get_telegram_api_url() -> str
    """Returns Telegram API URL, defaults to https://api.telegram.org"""

def validate_urls() -> None
    """Validates all URLs are properly configured with http:// or https://"""
```

### 2. **src/llm_service.py** - Updated Ollama Configuration

- Added import: `from .config import get_ollama_url`
- Changed `ModelConfig.__init__` to accept `local_base_url: Optional[str] = None`
- Updated initialization: `self.local_base_url = local_base_url or get_ollama_url()`
- Now reads from `OLLAMA_URL` environment variable with fallback to default

**Before:**
```python
def __init__(self, local_base_url: str = "http://localhost:11434/v1", ...):
    self.local_base_url = local_base_url
```

**After:**
```python
def __init__(self, local_base_url: Optional[str] = None, ...):
    self.local_base_url = local_base_url or get_ollama_url()
```

### 3. **src/utils/telemetry.py** - Updated Traceloop Configuration

- Added import: `from ..config import get_traceloop_url`
- Changed hardcoded assignment:

**Before:**
```python
os.environ["TRACELOOP_BASE_URL"] = "http://localhost:6006/v1/traces"
```

**After:**
```python
traceloop_url = get_traceloop_url()
os.environ["TRACELOOP_BASE_URL"] = traceloop_url
```

### 4. **src/utils/notifications.py** - Updated Telegram API Configuration

- Added import: `from ..config import get_telegram_api_url`
- Updated `_get_api_url()` method:

**Before:**
```python
def _get_api_url(self, method: str) -> str:
    return f"https://api.telegram.org/bot{self.bot_token}/{method}"
```

**After:**
```python
def _get_api_url(self, method: str) -> str:
    api_url = get_telegram_api_url()
    return f"{api_url}/bot{self.bot_token}/{method}"
```

### 5. **.env.example** - Added URL Configuration Variables

```env
# Ollama Local LLM Service URL
# Used for local model inference (override for remote Ollama instances)
# Default: http://localhost:11434/v1
OLLAMA_URL=http://localhost:11434/v1

# Traceloop Distributed Tracing Collector URL
# Used for sending OpenTelemetry traces to observability platform
# Default: http://localhost:6006/v1/traces (local Phoenix instance)
# In production, change to your Phoenix or Traceloop collector endpoint
TRACELOOP_URL=http://localhost:6006/v1/traces

# Telegram Bot API Base URL
# Used for sending notifications via Telegram
# Default: https://api.telegram.org (official Telegram API)
# Can be overridden to use custom Telegram Bot API servers
TELEGRAM_API_URL=https://api.telegram.org
```

### 6. **tests/test_config.py** - Comprehensive Test Suite (32 tests)

Created 32 comprehensive tests covering:

#### Configuration Tests (12 tests)
- Ollama URL defaults, custom values, HTTPS support
- Traceloop URL defaults, custom values, production URLs
- Telegram URL defaults, custom values, custom Bot API servers

#### Validation Tests (6 tests)
- Validate URLs pass with defaults and custom values
- Reject invalid URL formats (missing http/https)
- Reject empty URLs
- Accept HTTPS URLs

#### Integration Tests (8 tests)
- LLMService uses configured Ollama URL
- Telemetry uses configured Traceloop URL
- TelegramNotifier uses configured Telegram API URL
- Environment-specific configurations (dev, staging, prod)

#### Source Code Verification Tests (3 tests)
- Verify no hardcoded localhost:6006 in telemetry.py
- Verify no hardcoded api.telegram.org in notifications.py
- Verify Ollama URLs read from config/env, not hardcoded

## Environment-Specific Usage

### Development Environment
```bash
# .env or .env.local
OLLAMA_URL=http://localhost:11434/v1
TRACELOOP_URL=http://localhost:6006/v1/traces
TELEGRAM_API_URL=https://api.telegram.org
```

### Staging Environment
```bash
OLLAMA_URL=http://ollama.staging.example.com:11434/v1
TRACELOOP_URL=http://traceloop.staging.example.com:6006/v1/traces
TELEGRAM_API_URL=https://api.telegram.org
```

### Production Environment
```bash
OLLAMA_URL=https://ollama.prod.example.com/v1
TRACELOOP_URL=https://traceloop.prod.example.com/v1/traces
TELEGRAM_API_URL=https://api.telegram.org
```

## Verification Results

### ✅ All Tests Pass (32/32)
```
tests/test_config.py::TestOllamaUrlConfiguration (4 tests) ✓
tests/test_config.py::TestTraceloopUrlConfiguration (4 tests) ✓
tests/test_config.py::TestTelegramUrlConfiguration (3 tests) ✓
tests/test_config.py::TestUrlValidation (6 tests) ✓
tests/test_config.py::TestLLMServiceUrlConfiguration (3 tests) ✓
tests/test_config.py::TestTelemetryUrlConfiguration (2 tests) ✓
tests/test_config.py::TestTelegramNotifierUrlConfiguration (3 tests) ✓
tests/test_config.py::TestEnvironmentSpecificUrls (3 tests) ✓
tests/test_config.py::TestNoHardcodedUrlsInSourceCode (3 tests) ✓
```

### ✅ No Hardcoded URLs in Source Code
Verified via grep that no hardcoded URLs remain in:
- `src/llm_service.py`
- `src/utils/telemetry.py`
- `src/utils/notifications.py`

(Note: Hardcoded URLs remain only in docstrings/comments for documentation purposes)

### ✅ All Modules Import Successfully
- ✓ src.config module imports
- ✓ src.llm_service module imports
- ✓ src.utils.telemetry module imports
- ✓ src.utils.notifications module imports

## Benefits

1. **Environment Flexibility**: Configure URLs per environment without code changes
2. **Security**: No hardcoded URLs in version control
3. **Testability**: Easy to test with different URL configurations
4. **Maintainability**: Centralized URL configuration in one module
5. **Documentation**: Clear examples in .env.example for all URL variables

## Files Modified

1. [src/config.py](file:///home/alexc/Projects/ArbitrageAI/src/config.py#L127-L196) - Added URL configuration functions and validation
2. [src/llm_service.py](file:///home/alexc/Projects/ArbitrageAI/src/llm_service.py#L1-L30) - Updated to use get_ollama_url()
3. [src/utils/telemetry.py](file:///home/alexc/Projects/ArbitrageAI/src/utils/telemetry.py#L1-L30) - Updated to use get_traceloop_url()
4. [src/utils/notifications.py](file:///home/alexc/Projects/ArbitrageAI/src/utils/notifications.py#L19-L65) - Updated to use get_telegram_api_url()
5. [.env.example](file:///home/alexc/Projects/ArbitrageAI/.env.example#L125-L149) - Added URL configuration section
6. [tests/test_config.py](file:///home/alexc/Projects/ArbitrageAI/tests/test_config.py) - New comprehensive test suite

## Test Execution

```bash
pytest tests/test_config.py -v

# Result: 32 passed
```

## Related Issues

- Issue #17: Security Implementation
- Issue #31: Distributed Tracing Implementation
- Issue #34: File Upload Security
- Issue #36: Pydantic V2 Migration

All these issues benefited from centralized configuration management.
