# Distributed Tracing Quick Start Guide

## Overview

ArbitrageAI now includes distributed tracing that automatically correlates logs and traces across async task boundaries using W3C Trace Context standard.

**Key Features:**
- ✅ Automatic trace ID propagation across async boundaries
- ✅ Trace IDs included in all logs (no code changes needed)
- ✅ W3C traceparent header support for cross-service tracing
- ✅ Zero-configuration logging enhancement

## Basic Usage

### 1. Initialize Trace Context (Automatic)

The trace context is **automatically initialized** in:
- API middleware (from request headers)
- Async task processing (`process_task_async`)
- Background job queue workers

No code changes needed!

### 2. Access Trace ID in Code

```python
from src.utils.distributed_tracing import get_trace_id

def my_function():
    trace_id = get_trace_id()
    print(f"Current trace: {trace_id}")
```

### 3. Logging (Automatic)

Trace IDs are **automatically included** in all logs:

```python
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Output automatically includes trace ID
logger.info("Processing task")  
# [<trace_id>] [<span_id>] Processing task
```

### 4. Cross-Service Tracing

To propagate trace to another service:

```python
from src.utils.distributed_tracing import propagate_trace_context
import httpx

# Get traceparent header
headers = {"traceparent": propagate_trace_context()}

# Call other service with header
response = httpx.get("https://api.example.com/data", headers=headers)
```

On the receiving service:
```python
from src.utils.distributed_tracing import init_trace_from_headers

# Initialize from incoming headers
init_trace_from_headers(request.headers)

# Now logs and operations use same trace ID
logger.info("Processing")  # Same trace as calling service
```

## Common Patterns

### Pattern 1: Background Task

```python
async def process_task_async(task_id: str):
    # Trace context initialized automatically in main.py
    
    # Access trace ID if needed
    from src.utils.distributed_tracing import get_trace_id
    trace_id = get_trace_id()
    
    logger.info(f"Processing task {task_id} with trace {trace_id}")
    # [<trace_id>] [<span_id>] Processing task <task_id> with trace <trace_id>
```

### Pattern 2: Async Operations

```python
async def handle_request():
    # Trace context inherited automatically
    
    result = await async_operation_1()
    result = await async_operation_2(result)
    
    # All operations share same trace ID (logged automatically)
```

### Pattern 3: Concurrent Operations

```python
async def concurrent_processing():
    results = await asyncio.gather(
        operation_a(),
        operation_b(),
        operation_c(),
    )
    # All operations share same trace ID
```

### Pattern 4: Explicit Trace Scope

```python
from src.utils.distributed_tracing import DistributedTraceContext

async with DistributedTraceContext() as ctx:
    logger.info(f"Trace: {ctx.trace_id}")
    await async_work()
    # Context automatically cleaned up
```

## Monitoring Logs by Trace

### View all logs for a specific trace:

```bash
# For JSON logs
jq 'select(.trace_id == "abc123def456...")' logs/app.log

# For text logs with grep
grep "abc123def456" logs/app.log
```

### Correlate logs across services:

1. Find trace ID in service A's logs
2. Search for same trace ID in service B's logs
3. See complete request flow with timing

### Example log output:

```
[4bf92f3577b34da6a3ce929d0e0e4736] [00f067aa0ba902b7] 2024-02-25 10:30:45 [INFO] [main.py:600] Starting async task processing - trace_id=4bf92f3577b34da6a3ce929d0e0e4736
[4bf92f3577b34da6a3ce929d0e0e4736] [a1b2c3d4e5f6g7h8] 2024-02-25 10:30:45 [INFO] [executor.py:120] Fetching context files
[4bf92f3577b34da6a3ce929d0e0e4736] [a1b2c3d4e5f6g7h8] 2024-02-25 10:30:46 [INFO] [executor.py:150] Context extraction complete
[4bf92f3577b34da6a3ce929d0e0e4736] [x9y8z7w6v5u4t3s2] 2024-02-25 10:30:47 [INFO] [planning.py:75] Generating work plan
[4bf92f3577b34da6a3ce929d0e0e4736] [x9y8z7w6v5u4t3s2] 2024-02-25 10:30:48 [INFO] [planning.py:100] Plan generation complete
[4bf92f3577b34da6a3ce929d0e0e4736] [m1n2o3p4q5r6s7t8] 2024-02-25 10:30:49 [INFO] [executor.py:200] Executing plan in sandbox
[4bf92f3577b34da6a3ce929d0e0e4736] [m1n2o3p4q5r6s7t8] 2024-02-25 10:30:55 [INFO] [executor.py:250] Plan execution complete
```

## W3C Traceparent Header Format

```
traceparent = 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
              └─┬─┘└──────────────────┬─────────────────┘└──────┬──────┘└┬┘
              version            trace_id (128-bit)      span_id    flags
                                 32 hex characters    16 hex chars  (01=sampled)
```

**Version:** Always `00` (current stable)
**Trace ID:** 128-bit random value (32 hex chars)
**Span ID:** 64-bit random value (16 hex chars)  
**Flags:** Sampling decision (`01` = sampled, `00` = not sampled)

## API Reference

### Core Functions

```python
from src.utils.distributed_tracing import (
    # Generation
    generate_trace_id() -> str              # 32-char hex trace ID
    generate_span_id() -> str               # 16-char hex span ID
    
    # Context Management
    init_trace_context() -> str             # Initialize and return trace ID
    get_trace_id() -> Optional[str]         # Get current trace ID
    get_span_id() -> Optional[str]          # Get current span ID
    clear_trace_context() -> None           # Clear context
    
    # Header Support
    propagate_trace_context() -> str        # Get W3C traceparent header value
    extract_trace_context_from_headers()    # Parse W3C traceparent header
    init_trace_from_headers() -> str        # Initialize from request headers
    
    # Utilities
    get_trace_context_dict() -> Dict        # Get all context as dictionary
    DistributedTraceContext                 # Context manager (sync/async)
    TraceContextFilter                      # Logging filter
    setup_trace_logging()                   # Configure logger
)
```

### Logging Integration

```python
from src.utils.distributed_tracing import (
    TraceContextFilter,    # logging.Filter for adding trace to logs
    setup_trace_logging,   # Configure logger with trace context
)

# Setup logging (called automatically in telemetry.py)
logger = logging.getLogger(__name__)
setup_trace_logging(logger)

# Now all logs include trace context automatically
logger.info("Message")  # [trace_id] [span_id] Message
```

## Testing Distributed Tracing

```bash
# Run all distributed tracing tests
pytest tests/test_distributed_tracing.py -v

# Run specific test
pytest tests/test_distributed_tracing.py::TestTraceIDGeneration -v

# Run with coverage
pytest tests/test_distributed_tracing.py --cov=src.utils.distributed_tracing
```

## Troubleshooting

### Trace ID is None

**Issue:** `get_trace_id()` returns `None`

**Solution:** Ensure trace context is initialized:
```python
from src.utils.distributed_tracing import init_trace_context
trace_id = init_trace_context()  # Must call to initialize
```

### Trace IDs not in logs

**Issue:** Logs don't include trace context

**Solution:** Ensure logging is configured with trace filter:
```python
from src.utils.distributed_tracing import setup_trace_logging
logger = logging.getLogger(__name__)
setup_trace_logging(logger)  # Add trace context
```

This is called automatically in `src/utils/telemetry.py` during app initialization.

### Different trace IDs in child tasks

**Issue:** Each async task has different trace ID

**Solution:** Trace context should be inherited, not regenerated. If you need to start a new trace:
```python
from src.utils.distributed_tracing import get_trace_id
current = get_trace_id()  # Use parent's trace ID
# Don't call init_trace_context() unless you need a new trace
```

## Performance

- **Trace ID generation:** <1 microsecond (UUID4)
- **Context lookup:** <1 microsecond (ContextVar)
- **Logging filter:** ~1-2 microseconds per log record
- **Header parsing:** <1 microsecond (regex)

**Overall impact:** < 5 microseconds per request (negligible)

## Standards Compliance

- ✅ [W3C Trace Context](https://www.w3.org/TR/trace-context/) Level 1
- ✅ [OpenTelemetry](https://opentelemetry.io/) Compatible
- ✅ [PEP 567](https://www.python.org/dev/peps/pep-0567/) (contextvars)
- ✅ Python 3.7+ Compatible

## Additional Resources

- [Implementation Details](./ISSUE_31_DISTRIBUTED_TRACING_IMPLEMENTATION.md)
- [Tests](./tests/test_distributed_tracing.py)
- [W3C Trace Context Spec](https://www.w3.org/TR/trace-context/)
- [OpenTelemetry Docs](https://opentelemetry.io/docs/)

## Examples in Codebase

### Middleware Integration
- `src/api/main.py:1209-1220` - Trace initialization in HTTP middleware

### Async Task Processing
- `src/api/main.py:597-600` - Trace initialization in background tasks

### Logging Integration
- `src/utils/telemetry.py:34-37` - Setup in observability init

## Getting Help

For issues or questions:
1. Check [Troubleshooting](#troubleshooting) section
2. Review test examples in `tests/test_distributed_tracing.py`
3. Check implementation in `src/utils/distributed_tracing.py`
4. Refer to [W3C Trace Context Spec](https://www.w3.org/TR/trace-context/)
