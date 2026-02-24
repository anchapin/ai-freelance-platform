# Subagent Task: GitHub Issue #8

**Repository**: /home/alexc/Projects/ArbitrageAI  
**Worktree**: main-issue-8  
**Branch**: feature/issue-8  
**GitHub Issue**: #8 - Implement distributed lock and deduplication for marketplace bids

## Task Overview

You are working on GitHub Issue #8 in an isolated git worktree. Your task is to implement a distributed lock system and deduplication logic to prevent race conditions when multiple scanner instances place bids on the same marketplace posting.

## Implementation Checklist

### Phase 1: Model Extensions
- [ ] Modify `src/api/models.py`:
  - [ ] Add `BidStatus.ACTIVE`, `BidStatus.WITHDRAWN`, `BidStatus.DUPLICATE` enums
  - [ ] Add `withdrawn_reason` field to Bid model
  - [ ] Add `withdrawal_timestamp` field to Bid model  
  - [ ] Add `posting_cached_at` field to Bid model
  - [ ] Add unique constraint: (marketplace, job_id) WHERE status='ACTIVE'
  - [ ] Update `to_dict()` method to include new fields

### Phase 2: Distributed Lock Manager
- [ ] Create `src/agent_execution/bid_lock_manager.py`:
  - [ ] Implement `BidLock` dataclass with TTL tracking
  - [ ] Implement `BidLockManager` class with:
    - [ ] `acquire_lock(marketplace_id, posting_id, timeout=10)` - async method
    - [ ] `release_lock(marketplace_id, posting_id)` - async method
    - [ ] `with_lock(marketplace_id, posting_id)` - async context manager
    - [ ] Lock expiration tracking and cleanup
    - [ ] Metrics: lock_attempts, lock_successes, lock_conflicts, lock_timeouts

### Phase 3: Deduplication Logic
- [ ] Add to `src/agent_execution/market_scanner.py`:
  - [ ] Import and initialize BidLockManager
  - [ ] Create `should_bid(db_session, posting_id, marketplace_id)` async function
  - [ ] Check for existing ACTIVE bids on same posting
  - [ ] Implement posting freshness validation (24-hour TTL)
  - [ ] Integrate with main bidding flow using lock context manager

### Phase 4: Bid Withdrawal Handler
- [ ] Create `src/agent_execution/bid_withdrawal.py`:
  - [ ] Implement marketplace-specific withdrawal handlers
  - [ ] Update Bid.status to WITHDRAWN on successful withdrawal
  - [ ] Track withdrawal_reason and withdrawal_timestamp
  - [ ] Implement retry logic for failed withdrawals
  - [ ] Log failures for manual review

### Phase 5: Integration & Testing
- [ ] Create `tests/test_marketplace_dedup.py`:
  - [ ] Test concurrent bid scenarios (2+ concurrent bids on same posting)
  - [ ] Test deduplication prevents duplicate ACTIVE bids
  - [ ] Test distributed lock timeout and recovery
  - [ ] Test bid withdrawal functionality
  - [ ] Test posting freshness validation
  - [ ] Performance test: no bids on same posting within 5-minute window
  - [ ] Race condition test with 100+ concurrent bid attempts

## Key Requirements

1. **Distributed Lock**: 
   - Lock key format: `bid:lock:{marketplace_id}:{posting_id}`
   - TTL: 5 minutes (300 seconds)
   - Timeout: 10 seconds maximum wait time
   - Handle lock expiration gracefully

2. **Deduplication**:
   - Check database for ACTIVE bids before placing new bid
   - Unique constraint at database level: (marketplace, job_id, status='ACTIVE')
   - Return early if duplicate detected

3. **Posting Freshness**:
   - Add TTL validation for cached postings (24 hours default)
   - Skip stale postings (older than TTL)
   - Store cache timestamp in posting_cached_at field

4. **Bid Withdrawal**:
   - Marketplace-specific withdrawal handlers
   - Status transitions: ACTIVE → WITHDRAWN → REJECTED
   - Track reason and timestamp
   - Retry failed withdrawals with exponential backoff

5. **Testing Requirements**:
   - 100% coverage for deduplication logic
   - Race condition tests with concurrent execution
   - Integration tests with actual database
   - Performance benchmark: 1000+ bids without issues

## Files to Modify

1. `src/api/models.py` - Extend Bid model
2. `src/agent_execution/market_scanner.py` - Integrate lock manager
3. Create `src/agent_execution/bid_lock_manager.py` - Lock implementation
4. Create `src/agent_execution/bid_withdrawal.py` - Withdrawal handlers
5. Create `tests/test_marketplace_dedup.py` - Comprehensive tests

## Testing Commands

```bash
# Run tests
pytest tests/test_marketplace_dedup.py -v --cov=src/agent_execution

# Run specific test
pytest tests/test_marketplace_dedup.py::test_concurrent_bids -v

# Check for race conditions
pytest tests/test_marketplace_dedup.py::test_race_condition_100_concurrent -v
```

## Acceptance Criteria

- [x] Models updated with new fields and constraints
- [x] BidLockManager implemented and tested
- [x] Deduplication logic prevents duplicate ACTIVE bids
- [x] Bid withdrawal handler works for all marketplace types
- [x] All tests passing with 100% coverage
- [x] No duplicate bids in 1000+ task run
- [x] No resource leaks or deadlocks

## Timeline

Expected completion: 5-6 hours

## Notes

- Financial risk: test thoroughly before merging
- This shares code paths with Issue #4 (Playwright leaks) in market_scanner.py
- Consider using Redis for distributed locking in future (currently in-memory)
- Coordinate with Issue #4 when integrating both changes
