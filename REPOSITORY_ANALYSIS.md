# ArbitrageAI Repository Analysis

**Date**: February 24, 2026  
**Scope**: Architecture complexity review and improvement roadmap

---

## Overview

This analysis identified **7 difficulty areas** requiring architectural improvements. All issues have been created as GitHub issues (see links below) with detailed specifications and acceptance criteria.

---

## 7 Difficulty Areas

### 🔴 CRITICAL (P0) - Fix This Week

#### 1. Agent Arena Profitability Tests
**GitHub Issue**: [#2](https://github.com/anchapin/ArbitrageAI/issues/2)  
**Effort**: 3-4 hours  
**Problem**: Missing test coverage for edge cases in profit calculations. Hardcoded pricing with no dynamic fallback. Can lead to incorrect winner selection (cloud vs local model).  
**Files**: `src/agent_execution/arena.py`, `src/api/main.py`  
**Impact**: Direct effect on profitability  
**Acceptance Criteria**:
- 95%+ branch coverage for arena.py
- Tests for negative profit, ties, zero revenue scenarios
- Dynamic pricing validation

#### 2. HITL Escalation Idempotency
**GitHub Issue**: [#3](https://github.com/anchapin/ArbitrageAI/issues/3)  
**Effort**: 4-5 hours  
**Problem**: Potential duplicate Telegram notifications on retry. Database state updated before notification, causing inconsistency if notification fails. No transaction wrapping.  
**Files**: `src/api/main.py`, `src/utils/notifications.py`, `src/api/models.py`  
**Impact**: User satisfaction, audit trail integrity  
**Acceptance Criteria**:
- EscalationLog model to track events
- Idempotency key prevents duplicate notifications
- Entire workflow wrapped in database transaction

---

### 🟠 HIGH (P1) - Fix by Week 4

#### 3. Playwright Resource Leaks
**GitHub Issue**: [#4](https://github.com/anchapin/ArbitrageAI/issues/4)  
**Effort**: 5-6 hours  
**Problem**: Missing async context managers in web scraping. No browser/page cleanup on exceptions. Can exhaust file descriptors after 1000+ tasks.  
**Files**: `src/agent_execution/market_scanner.py`, `src/agent_execution/marketplace_discovery.py`  
**Impact**: System-wide resource exhaustion, potential outages  
**Acceptance Criteria**:
- All Playwright resources use async context managers
- Resource leak detection test (verify no fd growth over 1000 tasks)
- Circuit breaker for failing marketplace URLs

#### 4. Task Model Overload
**GitHub Issue**: [#5](https://github.com/anchapin/ArbitrageAI/issues/5)  
**Effort**: 8-10 hours  
**Problem**: Single Task model has 30+ columns mixing execution, planning, review, arena, and file storage concerns. ~15 nullable fields with unclear semantics. No state machine validation.  
**Files**: `src/api/models.py`, `src/api/database.py`  
**Impact**: Code maintainability, testing difficulty, schema migration overhead  
**Acceptance Criteria**:
- Task model reduced to <15 core fields
- New composition entities: TaskExecution, TaskPlanning, TaskReview, TaskArena, TaskOutput
- State machine validation (impossible transitions prevented)
- Database migration script provided

#### 5. RAG Integration Coupling
**GitHub Issue**: [#6](https://github.com/anchapin/ArbitrageAI/issues/6)  
**Effort**: 6-8 hours  
**Problem**: ChromaDB and Distillation modules tightly coupled to task execution. If either fails, entire task fails. Fallback to zero-shot prompting adds latency. Distillation capture blocks task completion.  
**Files**: `src/experience_vector_db.py`, `src/agent_execution/executor.py`, `src/distillation/dataset_manager.py`  
**Impact**: Reliability and performance degradation  
**Acceptance Criteria**:
- Task execution succeeds even if ChromaDB unavailable
- Async background job queue for distillation capture
- Cache for few-shot queries with circuit breaker
- Metrics for RAG hit rates and fallback rates

#### 6. Marketplace Bid Deduplication
**GitHub Issue**: [#8](https://github.com/anchapin/ArbitrageAI/issues/8)  
**Effort**: 5-6 hours  
**Problem**: No distributed lock for concurrent bid placement. Multiple scanner instances can create duplicate bids on same posting. Race conditions between scanner and human bidders. No mechanism to withdraw failed bids.  
**Files**: `src/agent_execution/market_scanner.py`, `src/agent_execution/marketplace_discovery.py`, `src/api/models.py`  
**Impact**: Duplicate proposals, financial loss, reputation damage  
**Acceptance Criteria**:
- Distributed lock prevents concurrent bids on same posting
- Deduplication check before bid placement
- Bid withdrawal functionality with status tracking
- 100% test coverage for concurrency scenarios

---

### 🟡 MEDIUM (P2) - Fix by Week 8

#### 7. Ollama Health Check & Circuit Breaker
**GitHub Issue**: [#7](https://github.com/anchapin/ArbitrageAI/issues/7)  
**Effort**: 3-4 hours  
**Problem**: No health checks before routing tasks to local Ollama. Fallback chain wastes 90+ seconds on unavailable service (3 × 30s timeouts). No circuit breaker pattern.  
**Files**: `src/llm_service.py`, `src/utils/telemetry.py`  
**Impact**: Task completion latency, poor user experience  
**Acceptance Criteria**:
- Health checks run every 30 seconds
- Circuit breaker reduces max latency to <40 seconds
- Exponential backoff for retries
- Metrics exported for observability

---

## Implementation Roadmap

### Phase 1: Immediate (Week 1) - 7-9 hours
**Focus**: Critical financial and user-facing correctness
- Issue #2: Arena Profitability Tests (3-4h)
- Issue #3: HITL Escalation Idempotency (4-5h)

**Success Criteria**:
- ✓ 95%+ test coverage for profit calculations
- ✓ Zero duplicate escalation notifications
- ✓ Transaction-safe database operations

### Phase 2: Short-term (Weeks 2-4) - 13-16 hours
**Focus**: System reliability and failure prevention
- Issue #4: Playwright Cleanup (5-6h)
- Issue #8: Marketplace Deduplication (5-6h)
- Issue #7: Ollama Circuit Breaker (3-4h)

**Success Criteria**:
- ✓ No resource leaks after 10,000 tasks
- ✓ Zero duplicate bids in 24-hour window
- ✓ Max fallback latency <40 seconds

### Phase 3: Medium-term (Weeks 5-8) - 14-18 hours
**Focus**: Architecture modernization
- Issue #5: Task Model Refactoring (8-10h)
- Issue #6: RAG Decoupling (6-8h)

**Success Criteria**:
- ✓ Task model <15 core fields
- ✓ RAG unavailability doesn't block task execution
- ✓ 90%+ overall test coverage

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| Total Issues | 7 |
| Critical (P0) | 2 |
| High (P1) | 4 |
| Medium (P2) | 1 |
| Total Implementation Effort | 34-43 hours |
| Duration | 8 weeks (3 phases) |
| Files Affected | 15+ core files |
| Test Coverage Gaps | 6 major areas |

---

## Getting Started

1. **Managers**: Review this document, note the 3 phases and effort breakdown
2. **Developers**: 
   - Start with Issue #2 (highest priority)
   - Use GitHub issue descriptions for detailed specs and code examples
   - Follow the implementation order above
3. **QA**: Review acceptance criteria in each GitHub issue for test requirements

---

## Key Resources

- **All Issues**: https://github.com/anchapin/ArbitrageAI/issues?label=complexity-analysis
- **Project Docs**: See `CLAUDE.md` for architecture overview
- **Setup Guide**: See `README.md` for development environment setup

---

## Additional Notes

- All 7 issues are created on GitHub with detailed specifications
- Each issue includes acceptance criteria, affected files, and code examples
- Issues are labeled with `complexity-analysis` and priority levels (priority-p0, priority-p1, priority-p2)
- No changes required to this document as work progresses—track status in GitHub issues

**Status**: Ready for implementation  
**Last Updated**: February 24, 2026
