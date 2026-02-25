# Issue #27: Configuration Audit - Quick Reference

## What Changed

### 1. `.env.example` - Complete Rewrite
- **Before**: ~150 lines, missing 40+ variables
- **After**: ~350 lines, all 52 variables documented

```bash
# Copy to get started
cp .env.example .env

# Set required variables
export API_KEY="sk_..."
export STRIPE_SECRET_KEY="sk_test_..."
export STRIPE_WEBHOOK_SECRET="whsec_..."
```

### 2. Configuration Validation
Added to `src/config.py`:

```python
# Validate configuration at startup (fails if invalid)
validate_critical_env_vars()

# Get configuration inventory (secrets masked)
config = get_all_configured_env_vars()
```

### 3. Automatic Startup Validation
Application now fails at startup if configuration is invalid:

```bash
python -m uvicorn src.api.main:app
# If config invalid: "Configuration validation failed: ..."
# If config valid: Server starts normally
```

### 4. Comprehensive Tests
39 tests ensuring validation works correctly:

```bash
pytest tests/test_config.py -v
# All 39 tests PASS ✓
```

## The 52 Environment Variables

### Required (Production)
- `API_KEY` - OpenAI API key
- `STRIPE_SECRET_KEY` - Stripe secret
- `STRIPE_WEBHOOK_SECRET` - Stripe webhook secret

### Database
- `DATABASE_URL` - SQLAlchemy connection (default: SQLite)
- `REDIS_URL` - Redis connection (optional)

### LLM Models
- `CLOUD_MODEL` - GPT model (default: gpt-4o-mini)
- `LOCAL_MODEL` - Ollama model (default: llama3.2)
- `OLLAMA_URL` - Ollama endpoint (default: localhost:11434)

### Marketplace Scanning
- `AUTONOMOUS_SCAN_ENABLED` - Enable autonomous loop (default: false)
- `MARKET_SCAN_INTERVAL` - Scan frequency in seconds (default: 300)

### Delivery Tokens
- `DELIVERY_TOKEN_TTL_HOURS` - Token validity (default: 1 hour)
- `DELIVERY_MAX_FAILED_ATTEMPTS` - Lockout threshold (default: 5)

### Security
- `CLIENT_AUTH_SECRET` - HMAC key (required in production)
- `ANTIVIRUS_SERVICE` - File scan backend (default: mock)

### Other
- See `.env.example` for all 52 variables

## Common Operations

### Validate Configuration
```python
from src.config import validate_critical_env_vars

try:
    validate_critical_env_vars()
    print("✓ Configuration valid")
except ValueError as e:
    print(f"✗ Configuration invalid: {e}")
```

### Get Configuration Inventory
```python
from src.config import get_all_configured_env_vars

config = get_all_configured_env_vars()
for var, value in config.items():
    print(f"{var}: {value}")  # Secrets automatically masked
```

### Check Specific Configuration
```python
import os
from src.config import get_redis_url, get_database_url

redis_url = get_redis_url()
db_url = get_database_url()
print(f"Redis: {redis_url}")
print(f"Database: {db_url}")
```

## Production Checklist

Before deploying:

```bash
# 1. Set environment
export ENV=production

# 2. Generate secure CLIENT_AUTH_SECRET
export CLIENT_AUTH_SECRET=$(openssl rand -hex 32)

# 3. Set Stripe keys (from production account)
export STRIPE_SECRET_KEY="sk_live_..."
export STRIPE_WEBHOOK_SECRET="whsec_..."

# 4. Configure database
export DATABASE_URL="postgresql://user:pass@host/db"

# 5. Configure Redis
export REDIS_URL="redis://:password@host:6379/0"

# 6. Verify configuration
python -c "from src.config import validate_critical_env_vars; validate_critical_env_vars(); print('✓ Config valid')"

# 7. Start application
python -m uvicorn src.api.main:app
```

## Troubleshooting

### API Key Error
```
Configuration validation failed:
  LLM API key not configured: set either API_KEY or OPENAI_API_KEY
```

**Fix**: Set either API_KEY or OPENAI_API_KEY environment variable

### Stripe Key Error (Production)
```
Configuration validation failed:
  STRIPE_SECRET_KEY not set (required in production)
```

**Fix**: Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET in production

### Invalid Integer Parameter
```
Configuration validation failed:
  Invalid delivery token configuration: invalid literal for int()
```

**Fix**: Ensure DELIVERY_TOKEN_TTL_HOURS, MIN_BID_AMOUNT, etc. are valid integers

### Insecure Secret (Production)
```
Configuration validation failed:
  CLIENT_AUTH_SECRET using insecure default in production.
```

**Fix**: Generate secure key: `openssl rand -hex 32`

## Files Modified

| File | Changes |
|------|---------|
| `.env.example` | Complete rewrite with 52 variables |
| `src/config.py` | Added validation and inventory functions |
| `src/api/main.py` | Integrated validation at startup |
| `tests/test_config.py` | New: 39 comprehensive tests |

## Test Results

```
tests/test_config.py ........... 39 PASSED ✓
```

Coverage:
- Configuration validation logic
- Environment variable handling
- Default value application
- Type validation
- Production vs development modes
- Secret masking
- URL validation

## Benefits

✅ **Fail-Fast**: Invalid config caught at startup, not at runtime
✅ **Complete**: All 52 variables documented in one place
✅ **Secure**: Secrets automatically masked in logs/output
✅ **Tested**: 39 tests ensure validation works
✅ **Self-Documenting**: Purpose and defaults for every variable
✅ **Production-Ready**: Separate requirements for production/development

## References

- Full documentation: [ISSUE_27_CONFIGURATION_AUDIT.md](file:///home/alexc/Projects/ArbitrageAI/ISSUE_27_CONFIGURATION_AUDIT.md)
- Configuration file: [.env.example](file:///home/alexc/Projects/ArbitrageAI/.env.example)
- Validation code: [src/config.py](file:///home/alexc/Projects/ArbitrageAI/src/config.py)
- Tests: [tests/test_config.py](file:///home/alexc/Projects/ArbitrageAI/tests/test_config.py)
