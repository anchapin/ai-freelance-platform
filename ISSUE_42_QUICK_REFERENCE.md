# Issue #42: APM Quick Reference

## Quick Start

### 1. Enable APM in Development
```bash
# APM is enabled by default (APM_ENABLED=true in .env)
docker-compose up -d
```

### 2. Access Monitoring UIs
- **Jaeger Traces:** http://localhost:16686
- **Prometheus Metrics:** http://localhost:9090
- **Grafana Dashboards:** http://localhost:3000 (admin/admin)

### 3. Run Tests
```bash
pytest tests/test_apm.py -v
# Result: 14 passed, 14 skipped
```

## Core Components

| Component | File | Purpose |
|-----------|------|---------|
| APM Manager | `src/utils/apm.py` | Core APM initialization, singleton |
| Tests | `tests/test_apm.py` | Comprehensive test suite (28 tests) |
| Telemetry | `src/utils/telemetry.py` | Integration with Phoenix/Traceloop |
| Dashboard | `src/utils/apm_dashboard.json` | Grafana dashboard definition |
| Docker | `docker-compose.yml` | APM services (Jaeger, Prometheus, Grafana) |
| Config | `.env.example` | APM environment variables |

## Key Functions

### Trace Critical Paths
```python
from src.utils.apm import (
    trace_task_execution,
    trace_llm_call,
    trace_marketplace_scan,
    trace_payment_processing,
    trace_rag_query,
    trace_arena_competition,
)

# Task execution with timing and attributes
with trace_task_execution(task_id="123", task_type="data_processing"):
    # Your code here
    pass

# LLM API calls
with trace_llm_call(model="gpt-4o", endpoint="https://api.openai.com/v1"):
    # OpenAI call
    pass

# Marketplace scanning
with trace_marketplace_scan(marketplace_url="https://freelancer.com/jobs"):
    # Scraping code
    pass

# Payment processing
with trace_payment_processing(payment_id="stripe-pi-123", amount=9999.00):
    # Stripe webhook handling
    pass

# Vector database queries
with trace_rag_query(query="...", top_k=5):
    # ChromaDB query
    pass

# A/B testing
with trace_arena_competition(competition_id="arena-456"):
    # Competition logic
    pass
```

### Decorate Functions
```python
from src.utils.apm import instrument_function

@instrument_function(span_name="custom.operation")
def my_function(x, y):
    return x + y
```

### Record Metrics
```python
from src.utils.apm import record_metric

# Success
record_metric("task_completion_counter", 1, {"status": "success"})

# Error
record_metric("task_error_counter", 1, {"error_type": "timeout"})

# Duration
record_metric("task_execution_time", 1234.5, {"task_type": "data"})
```

### Create Custom Spans
```python
from src.utils.apm import create_span

with create_span("bid.placement", {"marketplace": "freelancer"}) as span:
    # Bidding logic
    span.set_attribute("bid.status", "won")
```

## Metrics Collected

| Metric | Type | Unit | Use Case |
|--------|------|------|----------|
| `task.execution.time` | Histogram | ms | Task performance monitoring |
| `task.completion.total` | Counter | - | Success rate tracking |
| `task.error.total` | Counter | - | Error rate alerting |
| `llm.call.duration` | Histogram | ms | LLM API performance |
| `llm.token.usage` | Histogram | - | Cost analysis |
| `marketplace.scan.duration` | Histogram | ms | Marketplace optimization |
| `bid.placement.total` | Counter | - | Bidding volume |
| `payment.processing.duration` | Histogram | ms | Payment performance |
| `rag.query.duration` | Histogram | ms | Vector DB performance |
| `arena.competition.duration` | Histogram | ms | A/B test speed |
| `http.request.duration` | Histogram | ms | API latency |
| `http.request.total` | Counter | - | API request count |

## Environment Variables

```bash
# Enable/disable APM
APM_ENABLED=true                          # Default: true

# Choose backend
APM_BACKEND=jaeger                        # Options: jaeger, otlp

# Service identification
APM_SERVICE_NAME=arbitrage-ai             # Service name in traces
APM_VERSION=0.1.0                         # Service version
APM_ENVIRONMENT=development               # Environment label

# Trace sampling (important for production!)
TRACE_SAMPLE_RATE=1.0                     # Dev: 1.0, Prod: 0.1

# Jaeger configuration
JAEGER_ENDPOINT=http://localhost:14268/api/traces

# Prometheus configuration
PROMETHEUS_PORT=8001
PROMETHEUS_METRICS_PATH=/metrics
```

## Docker Commands

### Start All Services
```bash
docker-compose up -d
```

### Start Just APM Services
```bash
docker-compose up -d jaeger prometheus grafana
```

### View Logs
```bash
docker-compose logs jaeger      # Distributed tracing
docker-compose logs prometheus  # Metrics collection
docker-compose logs grafana     # Visualization
```

### Stop All Services
```bash
docker-compose down
```

## Grafana Dashboard Usage

### Access
http://localhost:3000
- **Username:** admin
- **Password:** admin

### Default Visualizations
1. **Task Execution Latency (p95/p99)** - Shows slowest task executions
2. **Task Completion Rate** - Tasks completed in last 5 minutes
3. **Task Error Rate** - Percentage of failed tasks
4. **LLM Call Latency** - API response times
5. **Payment Processing Latency** - Stripe processing time
6. **Marketplace Scan Latency** - Web scraping performance

### Create Custom Queries
Use Prometheus queries:
```
# Task error rate
rate(task_error_total[5m])

# P95 task execution time
histogram_quantile(0.95, rate(task_execution_time_bucket[5m]))

# Total tasks completed
increase(task_completion_total[5m])
```

## Jaeger Trace Inspection

### Access
http://localhost:16686

### View Distributed Traces
1. Select service: **arbitrage-ai**
2. Choose operation (e.g., "task.execution")
3. Click on trace to see full call stack
4. Inspect span attributes and timing

### Search Traces
- By service
- By operation name
- By duration (min/max)
- By tags/attributes

## Production Configuration

### Set Sampling Rate
```bash
# Reduce overhead in production
export TRACE_SAMPLE_RATE=0.1        # 10% sampling
export APM_ENVIRONMENT=production
export ENVIRONMENT=production
```

### Configure Persistent Storage
```bash
# Update docker-compose.yml to use external Jaeger
JAEGER_ENDPOINT=http://jaeger-prod.example.com:14268/api/traces
```

### Enable Alerting
Create Prometheus alert rules:
```yaml
- alert: HighErrorRate
  expr: rate(task_error_total[5m]) > 0.05
  for: 5m

- alert: SlowTaskExecution
  expr: histogram_quantile(0.95, rate(task_execution_time_bucket[5m])) > 5000
  for: 10m
```

## Test Coverage

### Run All APM Tests
```bash
pytest tests/test_apm.py -v
```

### Test Specific Class
```bash
pytest tests/test_apm.py::TestAPMManagerInitialization -v
```

### Test with Coverage
```bash
pytest tests/test_apm.py --cov=src/utils/apm --cov-report=html
```

## Troubleshooting

### APM Not Working
```bash
# Check APM is enabled
echo $APM_ENABLED                   # Should be "true"

# Verify Jaeger is running
docker-compose logs jaeger | tail -20

# Check metrics endpoint
curl http://localhost:8001/metrics
```

### No Traces in Jaeger
1. Verify `APM_ENABLED=true`
2. Check `JAEGER_ENDPOINT` is correct
3. Ensure Jaeger container is running
4. Check sampling rate is > 0

### Prometheus Not Scraping
1. Verify Prometheus config: `docker-compose exec prometheus cat /etc/prometheus/prometheus.yml`
2. Check targets: http://localhost:9090/targets
3. Verify FastAPI is exposing metrics on port 8001

### Grafana Dashboard Not Loading
1. Verify Prometheus datasource is working
2. Check dashboard JSON in Grafana UI
3. Refresh page (Ctrl+Shift+R)

## Performance Tips

1. **Set appropriate sampling rate**
   - Production: 0.05-0.1 (5-10%)
   - High-volume apps: 0.01 (1%)

2. **Use batch span processor** (default)
   - Reduces network overhead
   - Increases latency slightly (~5ms)

3. **Enable memory limiter**
   - Prevents unbounded trace buffering
   - Set in OTel Collector config

4. **Monitor APM overhead**
   - Should be < 1% CPU impact
   - Memory: ~10MB per 1000 active traces

## Integration Examples

### In Task Executor
```python
from src.utils.apm import trace_task_execution, record_metric

async def execute_task(task_id: str, task_type: str):
    with trace_task_execution(task_id, task_type):
        try:
            result = await do_work()
            record_metric("task_completion_counter", 1, {"status": "success"})
            return result
        except Exception as e:
            record_metric("task_error_counter", 1, {"error": str(type(e))})
            raise
```

### In LLM Service
```python
from src.utils.apm import trace_llm_call, record_metric

async def call_openai(model: str, prompt: str):
    with trace_llm_call(model, "https://api.openai.com/v1"):
        response = await openai.ChatCompletion.create(...)
        record_metric("llm_token_usage", response.usage.total_tokens)
        return response
```

### In Marketplace Scanner
```python
from src.utils.apm import trace_marketplace_scan

async def scan_marketplace(url: str):
    with trace_marketplace_scan(url):
        jobs = await fetch_jobs(url)
        return jobs
```

## Related Documentation

- [ISSUE_42_APM_INTEGRATION.md](ISSUE_42_APM_INTEGRATION.md) - Full documentation
- [DISTRIBUTED_TRACING_QUICK_START.md](DISTRIBUTED_TRACING_QUICK_START.md) - Tracing setup
- [OpenTelemetry Docs](https://opentelemetry.io/)
- [Jaeger Docs](https://www.jaegertracing.io/)
- [Grafana Docs](https://grafana.com/docs/)
