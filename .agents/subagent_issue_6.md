# Subagent Task: Issue #6

## Issue: Decouple Experience Vector Database from task execution flow

**Repository**: /home/alexc/Projects/ArbitrageAI  
**Worktree**: main-issue-6  
**Branch**: feature/vector-db-decouple  
**Priority**: P1

## Problem Statement
The Experience Vector Database (ChromaDB) and Distillation modules are tightly coupled to task execution, causing cascading failures when these secondary systems fail. Tasks fail entirely if ChromaDB is unavailable.

## Objective
Decouple ChromaDB and distillation to background async jobs so task execution succeeds even if these systems are unavailable.

## Implementation Tasks

### 1. Refactor experience_vector_db.py
**Lazy Initialization**:
- Don't initialize ChromaDB on module import
- Initialize only on first query
- Cache initialized client for reuse

**Connection Pooling**:
- Create `ChromaClientPool` class
- Maintain pool of 2-5 connections
- Reuse connections across queries
- Health check connections before use

**TTL & Cleanup**:
- Add TTL for cached experiences (configurable, default 7 days)
- Implement cleanup job to remove expired entries
- Remove orphaned entries (tasks deleted from SQL but not vector DB)

**Circuit Breaker**:
- Track consecutive failures
- Break circuit after 5 failures
- Pause for 60 seconds before retry
- Reset on successful query

### 2. Implement Async RAG Layer
Create `AsyncRAGService`:
```python
class AsyncRAGService:
    async def get_few_shot_examples(self, query: str, domain: str):
        # Queue background task
        # Return immediately with placeholder
        # Task populates few-shot examples when ready
        
    async def enrich_with_few_shot(self, base_prompt: str) -> str:
        # Non-blocking attempt to add few-shot
        # Return base_prompt if unavailable
```

**Caching Strategy**:
- Cache few-shot query results by (query_hash, domain)
- TTL: 1 hour
- Reduce repeated lookups for similar queries

### 3. Decouple Distillation
Move to async queue:
- Create `DistillationQueue` (async task queue)
- Capture task result to queue (don't block)
- Process queue in background worker
- Validate result before storing to ChromaDB
- Add retry logic with exponential backoff

### 4. Update executor.py Integration
**Modify task execution flow**:
```python
# Build zero-shot prompt first (no waiting)
system_prompt = build_zero_shot_system_prompt()

# Queue RAG enrichment in background (non-blocking)
enrich_task = asyncio.create_task(
    rag_service.enrich_with_few_shot(system_prompt)
)

# Execute task with zero-shot prompt
result = await execute_task_with_prompt(system_prompt)

# Optionally use enriched prompt if ready
try:
    enriched_prompt = enrich_task.result(timeout=2)
    # Could retry execution with enriched prompt
except asyncio.TimeoutError:
    pass  # Use original result

# Queue distillation (non-blocking)
asyncio.create_task(queue_distillation(result))

return result
```

### 5. Implement Async Background Processor
Create background job queue:
- Use task queue (e.g., RQ, Celery, or custom async queue)
- Process RAG enrichment tasks
- Process distillation tasks
- Implement retry logic with exponential backoff
- Add dead-letter queue for failed jobs

### 6. Add Metrics & Monitoring
Track:
- RAG hit rate (few-shot available / total queries)
- Fallback rate (zero-shot / total queries)
- Circuit breaker state (CLOSED/OPEN/HALF_OPEN)
- ChromaDB latency percentiles
- Distillation queue length
- Failed jobs count

## Files to Modify
- `src/experience_vector_db.py` - Major refactoring
- `src/agent_execution/executor.py` - Remove RAG blocking calls
- `src/distillation/dataset_manager.py` - Queue implementation
- `src/utils/background_queue.py` - New background job processor
- `src/utils/metrics.py` - Add metrics tracking
- `tests/test_vector_db_decouple.py` - New test file

## Testing Requirements
- ✓ Task execution succeeds when ChromaDB unavailable
- ✓ Distillation doesn't block task completion
- ✓ RAG queries processed in background
- ✓ Fallback to zero-shot works correctly
- ✓ Circuit breaker activates and resets
- ✓ Performance: task latency ±5% regardless of RAG availability
- ✓ Memory: background queue doesn't grow unbounded
- ✓ 90%+ coverage for fallback scenarios

## Acceptance Criteria
- [ ] Task execution succeeds if ChromaDB unavailable
- [ ] Distillation capture doesn't block task completion
- [ ] Async RAG layer implemented with caching
- [ ] Circuit breaker for ChromaDB working
- [ ] Background job processor working
- [ ] Metrics for hit/fallback rates exposed
- [ ] All tests passing
- [ ] Task latency unaffected by RAG availability

## Timeline
Estimated: 6-8 hours

## Notes
- Test with ChromaDB intentionally disabled
- Monitor background queue size in production
- Consider rate limiting RAG queries during recovery
- Coordinate with Issue #5 (Task model refactoring) - may affect executor paths
