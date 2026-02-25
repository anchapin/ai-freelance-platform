# Integration Guide: Redis Distributed Locks

## Quick Start (5 minutes)

### 1. Environment Setup

#### For Development (Uses In-Memory Fallback)
No action needed. If Redis isn't running, locks automatically fallback to in-memory implementation.

#### For Production (Requires Redis)
Set Redis connection in environment:
```bash
# Option A: Full URL
export REDIS_URL=redis://redis-host:6379/0

# Option B: Components
export REDIS_HOST=redis-host
export REDIS_PORT=6379
export REDIS_DB=0
export REDIS_PASSWORD=secret  # optional
```

### 2. Update Code to Use Factory

**Before (old code):**
```python
from src.agent_execution.bid_lock_manager import get_bid_lock_manager
manager = get_bid_lock_manager()
```

**After (new code):**
```python
from src.agent_execution.bid_lock_manager_factory import get_bid_lock_manager

# Auto-detects Redis or fallback
manager = await get_bid_lock_manager()
```

### 3. Use Context Manager (Recommended)

```python
async with manager.with_lock(
    marketplace_id="upwork",
    posting_id="job_123",
    timeout=10.0,
):
    # Your bid logic here
    await place_bid(posting_id, marketplace_id)
# Lock automatically released
```

### 4. Verify Installation

```bash
# Test Redis connection
python -c "
import asyncio
from src.agent_execution.redis_bid_lock_manager import RedisBidLockManager

async def test():
    m = RedisBidLockManager()
    if await m.health_check():
        print('✅ Redis connected')
        await m.close()
    else:
        print('⚠️ Redis unavailable (will use in-memory fallback)')

asyncio.run(test())
"

# Run tests
pytest tests/test_concurrent_bids.py -v
```

## API Reference

### `get_bid_lock_manager()`
Auto-detects Redis availability and returns appropriate manager.

```python
manager = await get_bid_lock_manager()  # Returns RedisBidLockManager or BidLockManager
```

### `create_bid_lock_manager(use_redis=None, ttl=300)`
Manually create a manager with specific configuration.

```python
# Force Redis
manager = await create_bid_lock_manager(use_redis=True, ttl=300)

# Force in-memory
manager = await create_bid_lock_manager(use_redis=False, ttl=300)

# Auto-detect
manager = await create_bid_lock_manager(use_redis=None, ttl=300)
```

### `manager.with_lock()` - Context Manager
Recommended approach for automatic cleanup.

```python
async with manager.with_lock(
    marketplace_id="upwork",
    posting_id="job_123",
    timeout=10.0,  # Maximum wait time
    holder_id="optional-instance-id",  # Auto-generated if not provided
):
    # Lock is held here
    await place_bid(posting_id, marketplace_id)
    # Lock automatically released on exit (even if exception)
```

### `manager.acquire_lock()` - Manual Acquisition
For fine-grained control.

```python
holder_id = "instance-1"
acquired = await manager.acquire_lock(
    marketplace_id="upwork",
    posting_id="job_123",
    timeout=10.0,
    holder_id=holder_id,
)

if acquired:
    try:
        await place_bid(posting_id, marketplace_id)
    finally:
        await manager.release_lock(
            marketplace_id="upwork",
            posting_id="job_123",
            holder_id=holder_id,
        )
```

### `manager.release_lock()`
Release a previously acquired lock.

```python
released = await manager.release_lock(
    marketplace_id="upwork",
    posting_id="job_123",
    holder_id="instance-1",
)
# Returns True if released, False if holder mismatch or not found
```

### `manager.get_metrics()`
Get lock performance metrics.

```python
metrics = manager.get_metrics()
# {
#     "lock_attempts": 100,
#     "lock_successes": 95,
#     "lock_conflicts": 5,
#     "lock_timeouts": 0,
#     "redis_errors": 0,  # Only for Redis implementation
# }
```

### `manager.health_check()`
Check Redis connectivity.

```python
is_healthy = await manager.health_check()
# Returns True if Redis is available
```

### `manager.cleanup_all()`
Force cleanup of all locks (testing/shutdown).

```python
await manager.cleanup_all()
```

## Production Deployment

### Prerequisites
- Redis 5.0+ running and accessible
- Network connectivity from all app instances to Redis
- Redis configured with sufficient memory (locks are small ~100 bytes each)

### Docker Compose Example
```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  app:
    image: arbitrageai:latest
    environment:
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_DB: 0
    depends_on:
      redis:
        condition: service_healthy

volumes:
  redis_data:
```

### Kubernetes ConfigMap
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: arbitrageai-config
data:
  REDIS_HOST: "redis.default.svc.cluster.local"
  REDIS_PORT: "6379"
  REDIS_DB: "0"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: arbitrageai
spec:
  replicas: 3  # Multiple instances
  template:
    spec:
      containers:
      - name: app
        envFrom:
        - configMapRef:
            name: arbitrageai-config
```

## Monitoring & Debugging

### Check Lock Status
```python
metrics = manager.get_metrics()
if metrics["lock_conflicts"] > 100:
    logger.warning("High lock contention detected")
if metrics["redis_errors"] > 0:
    logger.error(f"Redis errors: {metrics['redis_errors']}")
```

### View Redis Locks
```bash
# Connect to Redis
redis-cli

# List all bid locks
> KEYS bid_lock:*

# Check specific lock
> GET bid_lock:upwork:job_123

# Check TTL
> TTL bid_lock:upwork:job_123

# Clear all locks (development only!)
> FLUSHDB
```

### Enable Debug Logging
```python
import logging
logging.getLogger('src.agent_execution.redis_bid_lock_manager').setLevel(logging.DEBUG)
```

## Troubleshooting

### "Redis connection failed"
**Cause:** Redis not running or unreachable

**Solution:**
```bash
# Check Redis is running
redis-cli ping  # Should return PONG

# Check connection string
echo $REDIS_URL
# Should be: redis://host:port/db

# Verify network connectivity
telnet redis-host 6379
```

### "Lock timeout on bidding"
**Cause:** Contention - multiple instances trying same posting

**Solution:** This is expected behavior. One instance gets lock, others timeout.
- Monitor metrics for high contention
- Consider increasing timeout for non-urgent bids
- Scale up instances if contention is frequent

### "Holder mismatch for lock release"
**Cause:** Different process/instance tried to release lock

**Solution:** Ensure `holder_id` is consistent:
```python
# Use auto-generated holder_id (recommended)
async with manager.with_lock("upwork", "job_123"):
    pass  # holder_id auto-generated

# Or pass same holder_id for acquire/release
holder_id = "instance-1"
await manager.acquire_lock(..., holder_id=holder_id)
await manager.release_lock(..., holder_id=holder_id)
```

## Migration from Old Implementation

### Step 1: Update Imports
```python
# Old
from src.agent_execution.bid_lock_manager import get_bid_lock_manager

# New
from src.agent_execution.bid_lock_manager_factory import get_bid_lock_manager
```

### Step 2: Make Async
Old code might be sync. New factory is async:
```python
# Old (sync)
manager = get_bid_lock_manager()

# New (async required)
manager = await get_bid_lock_manager()
```

### Step 3: Update Bid Placement
```python
# Old
manager = get_bid_lock_manager()
if await manager.acquire_lock("upwork", "job_123", timeout=5.0):
    try:
        await place_bid("job_123", "upwork")
    finally:
        await manager.release_lock("upwork", "job_123")

# New (cleaner)
manager = await get_bid_lock_manager()
async with manager.with_lock("upwork", "job_123", timeout=5.0):
    await place_bid("job_123", "upwork")
```

## Testing

### Run All Tests
```bash
pytest tests/ -v
# 490 passed ✅
```

### Run Lock-Specific Tests
```bash
pytest tests/test_concurrent_bids.py tests/test_redis_bid_lock.py -v
# 35 passed ✅
```

### Test With Fallback
```bash
# Disable Redis to test fallback
USE_REDIS_LOCKS=false pytest tests/test_concurrent_bids.py -v
# 35 passed (using in-memory fallback) ✅
```

## Performance Tuning

### Lock TTL
- Default: 300 seconds (5 minutes)
- Shorter TTL: Faster recovery if instance crashes
- Longer TTL: Less chance of lock expiration during legitimate holds

```python
manager = await create_bid_lock_manager(ttl=180)  # 3 minutes
```

### Retry Parameters
(Auto-tuned, but can adjust in source if needed)
- Initial delay: 50ms
- Max delay: 1s
- Growth factor: 1.5x
- Reduces thundering herd on contention

### Redis Connection Pool
Auto-tuned with:
- Health check interval: 30s
- Socket timeout: 5s
- Socket keepalive: enabled

## Support

For issues:
1. Check logs: `grep -i "lock" logs/app.log`
2. Check Redis: `redis-cli KEYS bid_lock:*`
3. Check metrics: `manager.get_metrics()`
4. See [ISSUE_19_REDIS_DISTRIBUTED_LOCKING.md](ISSUE_19_REDIS_DISTRIBUTED_LOCKING.md) for details
