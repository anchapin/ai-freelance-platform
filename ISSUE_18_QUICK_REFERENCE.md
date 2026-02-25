# Issue #18: Security Validation - Quick Reference

## Validation Rules at a Glance

### URL Path Parameters
```
GET /api/delivery/{task_id}/{token}

task_id:  UUID format only (36 chars)
          Example: 550e8400-e29b-41d4-a716-446655440100

token:    Alphanumeric + dash + underscore (20-256 chars)
          Example: correct_token_string_1234567890abcdefgh
```

### Validation Models Created

#### 1. AddressValidationModel
```python
address: str       # 5-255 chars, alphanumeric+spaces+.,#&'()
city: str          # 2-100 chars, letters+spaces+apostrophe
postal_code: str   # 2-20 chars, alphanumeric+spaces+dash
country: str       # Exactly 2 chars, ISO 3166-1 alpha-2 (US, GB, DE)
```

#### 2. DeliveryAmountModel
```python
amount_cents: int   # 0-999,999,999 ($0.00 - $9,999,999.99)
currency: str       # 3 chars, ISO 4217 (USD, EUR, GBP)
```

#### 3. DeliveryTimestampModel
```python
created_at: datetime   # Must be <= now (not in future)
expires_at: datetime   # Must be > now and <= now + 365 days
                       # Logical ordering: created_at < expires_at
```

### Rate Limiting Configuration
```bash
# Environment variables
DELIVERY_TOKEN_TTL_HOURS=1              # Default: 1 hour
DELIVERY_MAX_FAILED_ATTEMPTS=5          # Default: 5 per task per hour
DELIVERY_LOCKOUT_SECONDS=3600           # Default: 1 hour
DELIVERY_MAX_ATTEMPTS_PER_IP=20         # Default: 20 per IP per hour
DELIVERY_IP_LOCKOUT_SECONDS=3600        # Default: 1 hour
CORS_ORIGINS=http://localhost:5173      # Comma-separated list
```

### Security Headers Applied
```
X-Content-Type-Options: nosniff          # MIME type sniffing
X-XSS-Protection: 1; mode=block          # XSS protection
X-Frame-Options: DENY                    # Clickjacking prevention
Cache-Control: no-store, no-cache        # Caching control (delivery endpoints)
Pragma: no-cache                         # Legacy cache control
Expires: 0                               # Legacy cache control
```

## Test Summary

### Validation Model Tests: 13
- Address: 4 tests (valid + 3 invalid scenarios)
- Amount: 4 tests (valid + 3 invalid scenarios)
- Timestamp: 5 tests (valid + 4 invalid scenarios)

### Endpoint Tests: 11
- Input validation: 2 tests (invalid format)
- Token handling: 4 tests (expired, used, invalid, missing)
- Rate limiting: 2 tests (task-level, IP-level)
- Security: 2 tests (headers, response)
- Success: 1 test (full flow)

## Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| 400 - "Invalid input" | Bad UUID or token format | Check URL format, use UUID and alphanumeric token |
| 403 - "Invalid token" | Wrong token value | Use correct token, check case sensitivity |
| 403 - "Already used" | Token reused | Token is one-time use only, request new link |
| 403 - "Expired" | Token TTL exceeded | Request new delivery link |
| 404 - "Not found" | Task doesn't exist | Check task_id, verify task completed |
| 400 - "Not ready" | Task not COMPLETED | Wait for task to complete |
| 429 - "Too many attempts" | Rate limited | Wait 1 hour or use different IP |

## Security Testing Checklist

- [ ] Test with invalid UUID (non-hex chars)
- [ ] Test with special characters in token
- [ ] Test with expired token
- [ ] Test with already-used token
- [ ] Make 5+ failed attempts to trigger task rate limiting
- [ ] Make 20+ failed attempts to trigger IP rate limiting
- [ ] Verify security headers in response
- [ ] Test address validation with SQL injection attempt
- [ ] Test amount validation with negative/excess values
- [ ] Test timestamp validation with future dates

## Files Modified

| File | Lines | Changes |
|------|-------|---------|
| src/api/main.py | +170 | 4 validation models, CORS, security headers |
| tests/test_api_endpoints.py | +370 | 24 new tests (13 validation + 11 endpoint) |

## Test Results
```
✅ 39 passed
⏭️  1 skipped
⚠️  60 warnings (Pydantic v1 deprecations - minor)
```

## Deployment Checklist
- [ ] Review changes in src/api/main.py
- [ ] Run: `pytest tests/test_api_endpoints.py -v`
- [ ] Verify all 39 tests pass
- [ ] Set CORS_ORIGINS in .env
- [ ] Set rate limiting limits in .env (optional)
- [ ] Deploy to staging
- [ ] Test with curl or Postman
- [ ] Deploy to production

## Example Test Commands

```bash
# Run all validation model tests
pytest tests/test_api_endpoints.py::TestDeliveryValidationModels -v

# Run all delivery endpoint tests
pytest tests/test_api_endpoints.py::TestDeliveryEndpoint -v

# Run specific test
pytest tests/test_api_endpoints.py::TestDeliveryEndpoint::test_delivery_invalid_token -v

# Run all tests
pytest tests/test_api_endpoints.py -v
```

## API Examples

### Valid Request
```bash
curl "http://localhost:8000/api/delivery/550e8400-e29b-41d4-a716-446655440100/correct_token_string_1234567890abcdefgh"

# Response (200 OK)
{
  "task_id": "550e8400-e29b-41d4-a716-446655440100",
  "title": "Market Research",
  "domain": "research",
  "result_type": "xlsx",
  "result_url": "https://example.com/results.xlsx",
  "delivered_at": "2026-02-24T12:00:00+00:00"
}
```

### Invalid Request (Bad UUID)
```bash
curl "http://localhost:8000/api/delivery/not-a-uuid/token"

# Response (400 Bad Request)
{
  "detail": "Invalid input: Invalid task_id format (must be UUID)"
}
```

### Rate Limited Request
```bash
# After 5 failed attempts on same task
curl "http://localhost:8000/api/delivery/550e8400-e29b-41d4-a716-446655440100/wrong_token"

# Response (429 Too Many Requests)
{
  "detail": "Too many failed attempts for this task. Try again later."
}
```

---

**Status:** ✅ Complete  
**Date:** February 24, 2026  
**Test Coverage:** 24 comprehensive tests
