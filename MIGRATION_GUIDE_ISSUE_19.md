# Migration Guide: Issue #19 - Distributed BidLockManager with Redis

## Overview

This document explains the migration from the old SQLite-based BidLockManager to the new Redis-backed RedisBidLockManager.

**Problem**: The old implementation used SQLite's database locks, which cannot work across multiple servers/instances. SQLite is single-process only. This causes duplicate bids in multi-instance deployments.

**Solution**: Replace with Redis-backed distributed locking using atomic SET with NX (compare-and-set).

---

## Architecture Comparison

### OLD: SQLite-Based Locking (Non-Distributed)

**File**: `src/agent_execution/bid_lock_manager.py` (before migration)

**How it worked**:
- Used SQLAlchemy ORM with a `DistributedLock` table
- Lock acquisition: INSERT with unique constraint on `lock_key`
- IntegrityError on conflict = lock held by another process
- Manual expiration cleanup job runs periodically
- Retry loop with `asyncio.sleep(0.1)` for polling

**Problems**:
1. **Single-Process**: SQLite cannot coordinate across multiple server instances
2. **Not Distributed**: If two servers run bid_lock_manager.py, they each have local database views
3. **Race Conditions**: Two instances can both think they acquired the lock
4. **Polling**: Sleeps in retry loops block event loop (anti-pattern in async code)
5. **Cleanup Overhead**: Requires periodic job to clean expired locks

**Vulnerable Code Pattern**:
```python
# Instance A sees: lock_key not in database
await asyncio.sleep(0.1)  # Blocks event loop
# Instance B also sees: lock_key not in database
# Both INSERT simultaneously -> Duplicate bids!
```

### NEW: Redis-Based Locking (Truly Distributed)

**File**: `src/agent_execution/redis_bid_lock_manager.py`

**How it works**:
- Uses Redis SET with NX (atomic compare-and-set)
- Lock acquisition: `redis.set(lock_key, holder_id, nx=True, ex=ttl)`
- Atomic at Redis protocol level (no race conditions)
- Automatic expiration via Redis EX (no cleanup job needed)
- Exponential backoff (not blocking event loop)

**Advantages**:
1. **Truly Distributed**: Single Redis instance coordinates across all servers
2. **Atomic**: SET NX is atomic at Redis level (no race windows)
3. **Auto-Expiring**: EX parameter auto-deletes expired locks (no cleanup)
4. **Fast**: In-memory, sub-millisecond latency
5. **Non-Blocking**: Uses exponential backoff instead of polling

**Safe Code Pattern**:
```python
# Instance A: SET key holder_a NX EX 300 -> SUCCESS
# Instance B: SET key holder_b NX EX 300 -> ALREADY_EXISTS (atomic failure)
# No race condition possible
```

---

## Migration Steps

### 1. Setup Redis

**Local Development**:
```bash
# Install Redis (macOS)
brew install redis
redis-server

# Install Redis (Ubuntu/Debian)
sudo apt-get install redis-server
redis-server

# Install Redis (Docker)
docker run -d -p 6379:6379 redis:7-alpine
```

**Production**:
- Use managed Redis (AWS ElastiCache, GCP Memorystore, etc.)
- Or self-hosted Redis cluster with replication

### 2. Update Environment

Create/update `.env`:
```bash
# Redis connection (required for Issue #19)
REDIS_URL=redis://localhost:6379/0

# Alternative: Use separate components
# REDIS_HOST=localhost
# REDIS_PORT=6379
# REDIS_DB=0
# REDIS_PASSWORD=your-password  # if auth enabled
```

### 3. Install Dependencies

```bash
pip install redis>=5.0.0
# or
pip install -r requirements.txt
```

### 4. Update Imports

**Before**:
```python
from src.agent_execution.bid_lock_manager import get_bid_lock_manager
```

**After**:
```python
from src.agent_execution.redis_bid_lock_manager import get_bid_lock_manager
# or
from src.agent_execution.redis_bid_lock_manager import init_bid_lock_manager
```

### 5. Update Usage

**Context Manager** (Recommended):
```python
async def place_bid(marketplace_id: str, posting_id: str):
    lock_manager = await get_bid_lock_manager()
    
    async with lock_manager.with_lock(
        marketplace_id=marketplace_id,
        posting_id=posting_id,
        timeout=10.0,  # Max wait time
    ):
        # Critical section - only one bid per posting
        if await should_bid(db_session, posting_id, marketplace_id):
            bid = await create_bid_atomically(...)
            return bid
```

**Manual Acquisition**:
```python
lock_manager = await get_bid_lock_manager()

# Acquire
acquired = await lock_manager.acquire_lock(
    marketplace_id="upwork",
    posting_id="job_123",
    timeout=10.0,
)

if acquired:
    try:
        # Perform bid operations
        await place_bid(...)
    finally:
        # Always release
        await lock_manager.release_lock(
            marketplace_id="upwork",
            posting_id="job_123",
        )
```

### 6. Update Tests

Old tests with SQLite:
```python
# Would test database IntegrityError
```

New tests with Redis:
```python
# Test Redis SET NX atomic behavior
@pytest.mark.asyncio
async def test_concurrent_lock_attempts(lock_manager):
    """Test that only one concurrent attempt succeeds."""
    results = await asyncio.gather(
        lock_manager.acquire_lock("upwork", "job_123", holder_id="h1", timeout=1.0),
        lock_manager.acquire_lock("upwork", "job_123", holder_id="h2", timeout=1.0),
        lock_manager.acquire_lock("upwork", "job_123", holder_id="h3", timeout=1.0),
    )
    # Exactly one should succeed
    assert sum(results) == 1
```

### 7. Initialize at Startup

In `src/api/main.py` or your app initialization:

```python
import asyncio
from src.agent_execution.redis_bid_lock_manager import init_bid_lock_manager

async def startup():
    """Initialize services at app startup."""
    try:
        lock_manager = await init_bid_lock_manager()
        logger.info("✓ Distributed lock manager initialized")
    except RuntimeError as e:
        logger.error(f"✗ Failed to initialize lock manager: {e}")
        raise
```

### 8. Health Checks

Add Redis health check to your monitoring:

```python
async def health_check():
    """Check system health."""
    lock_manager = await get_bid_lock_manager()
    
    is_healthy = await lock_manager.health_check()
    if not is_healthy:
        logger.error("Redis connection failed")
        return {"status": "degraded", "redis": False}
    
    return {"status": "healthy", "redis": True}
```

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379/0` | Full Redis connection URL |
| `REDIS_HOST` | `localhost` | Redis host (if not using REDIS_URL) |
| `REDIS_PORT` | `6379` | Redis port (if not using REDIS_URL) |
| `REDIS_DB` | `0` | Redis database number (if not using REDIS_URL) |
| `REDIS_PASSWORD` | (empty) | Redis password (if not using REDIS_URL) |

### Lock Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ttl` | `300` | Lock time-to-live in seconds (5 minutes) |
| `timeout` | `10.0` | Max wait time for lock acquisition |

### Lock Key Format

```
bid_lock:{marketplace_id}:{posting_id}

Examples:
- bid_lock:upwork:job_123
- bid_lock:fiverr:gig_456
- bid_lock:freelancer:project_789
```

### Holder ID Format

Generated automatically, includes:
- Hostname (for multi-instance debugging)
- Process ID (for multi-process debugging)
- UUID (for uniqueness)

Example: `ip-172-31-0-42:12345:a1b2c3d4`

---

## Backward Compatibility

### Deprecation Timeline

1. **Phase 1 (Current)**: Both old and new implementations available
2. **Phase 2 (Next Sprint)**: New implementation recommended, old marked deprecated
3. **Phase 3 (4 weeks)**: Old implementation removed

### Migration Path

1. Start using new `RedisBidLockManager` in new code
2. Update existing bid placement code to use new manager
3. Remove old `BidLockManager` and SQLite `DistributedLock` table

---

## Testing Strategy

### Unit Tests
```bash
pytest tests/test_redis_bid_lock.py -v
```

Tests cover:
- Lock acquisition/release
- Concurrent attempts (only one succeeds)
- Lock expiration (TTL)
- Error handling
- Metrics collection

### Integration Tests
```bash
pytest tests/test_marketplace_dedup.py -v
```

Tests cover:
- Complete bid placement workflow
- Multi-instance simulations
- Redis unavailability handling

### Load Testing
```bash
# Simulate 100 concurrent bid attempts on same posting
pytest tests/test_redis_bid_lock.py::test_concurrent_lock_attempts -v -n 100
```

---

## Troubleshooting

### "Connection refused" Error

**Problem**: `ConnectionRefusedError: Cannot connect to redis://localhost:6379/0`

**Solution**:
```bash
# Make sure Redis is running
redis-server

# Or use Docker
docker run -d -p 6379:6379 redis:7-alpine

# Check connection
redis-cli ping
# Should return: PONG
```

### "Authentication failed" Error

**Problem**: Redis requires password but none provided

**Solution**:
```bash
# Set password in .env
REDIS_URL=redis://:your-password@localhost:6379/0

# Or
REDIS_PASSWORD=your-password
```

### Lock Timeouts in Production

**Problem**: Frequently seeing "Failed to acquire lock within timeout"

**Solution**:
1. Check Redis latency: `redis-cli --latency`
2. Increase timeout: `timeout=20.0` (up from 10.0)
3. Check Redis CPU/memory usage
4. Consider Redis cluster for high throughput

### Stale Locks Not Expiring

**Problem**: Locks staying in Redis after TTL

**Solution**: This shouldn't happen with Redis SET EX. If it does:
```python
# Force cleanup (manual operation)
lock_manager = await get_bid_lock_manager()
await lock_manager.cleanup_all()
```

---

## Performance Characteristics

### Lock Acquisition Latency

**SQLite-based** (old):
- Successful: 1-5ms (database roundtrip)
- Conflict + timeout: 10s (polling loop)

**Redis-based** (new):
- Successful: 0.5-2ms (in-memory)
- Conflict + timeout: 10s (exponential backoff)

### Throughput

**SQLite-based**: 100-200 locks/second (limited by disk I/O)

**Redis-based**: 10,000+ locks/second (in-memory)

### Memory Usage

**SQLite-based**: Unlimited (stored on disk)

**Redis-based**: ~500 bytes per lock (configurable via TTL)

---

## Deployment Checklist

- [ ] Redis deployed and accessible from all app instances
- [ ] `.env` configured with REDIS_URL or components
- [ ] `redis>=5.0.0` added to `pyproject.toml`
- [ ] Startup code initializes lock manager
- [ ] Tests passing locally
- [ ] Integration tests passing
- [ ] Redis connection pooling configured
- [ ] Health checks added to monitoring
- [ ] Documentation updated for ops team
- [ ] Runbook created for Redis troubleshooting

---

## References

- [Redis Documentation](https://redis.io/docs/)
- [Redis SET Command](https://redis.io/commands/set/)
- [Python Redis Client](https://github.com/redis/redis-py)
- [Distributed Locking with Redis](https://redis.io/docs/manual/patterns/distributed-locks/)
- Issue #19: https://github.com/anchapin/ArbitrageAI/issues/19
- Issue #8: https://github.com/anchapin/ArbitrageAI/issues/8 (Marketplace Deduplication)

---

**Status**: Ready for Implementation  
**Version**: 1.0  
**Last Updated**: February 24, 2026
