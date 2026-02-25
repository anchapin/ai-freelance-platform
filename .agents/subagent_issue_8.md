# Subagent Task: Issue #8

## Issue: Implement distributed lock and deduplication for marketplace bids

**Repository**: /home/alexc/Projects/ArbitrageAI  
**Worktree**: main-issue-8  
**Branch**: feature/distributed-lock-dedup  
**Priority**: P1

## Problem Statement
The marketplace scanner can create duplicate bids on the same posting if multiple scanner instances run simultaneously or if the scanner runs twice within the caching window. This causes financial loss and reputation damage.

## Objective
Implement a distributed lock system and deduplication logic to prevent race conditions and duplicate bids.

## Implementation Tasks

### 1. Extend Bid Model (src/api/models.py)
- Add `status` field: Enum(ACTIVE, WITHDRAWN, REJECTED)
- Add `withdrawn_reason` field: Optional[str]
- Add `withdrawal_timestamp` field: Optional[datetime]
- Add unique constraint: (marketplace_id, posting_id) WHERE status='ACTIVE'
- Update relationships with Task model

### 2. Implement Distributed Lock (src/agent_execution/market_scanner.py)
Create `BidLockManager` class:
- Use Redis-based distributed lock (or in-memory lock with TTL)
- Lock key format: `bid:lock:{marketplace_id}:{posting_id}`
- TTL: 5 minutes
- Methods:
  - `acquire_lock(marketplace_id, posting_id, timeout=10)` → bool
  - `release_lock(marketplace_id, posting_id)` → bool
  - `with_lock(marketplace_id, posting_id)` → async context manager

### 3. Add Deduplication Logic
Create `should_bid(posting_id, marketplace_id)` function:
```python
async def should_bid(posting_id: str, marketplace_id: str) -> bool:
    # Check if ACTIVE bid already exists on this posting
    existing = db.query(Bid).filter_by(
        posting_id=posting_id,
        marketplace_id=marketplace_id,
        status='ACTIVE'
    ).first()
    return existing is None
```

### 4. Implement Bid Withdrawal
- Create withdrawal handler for each marketplace type
- Update Bid.status to WITHDRAWN when bid withdrawn
- Track withdrawal reason and timestamp
- Implement retry logic for failed withdrawals
- Log failures for manual review

### 5. Add Posting Freshness Check
- Add TTL validation for cached postings (24 hours)
- Check if posting still active before bidding
- Skip stale postings
- Update posting cache with TTL metadata

### 6. Integration with Market Scanner
Update main bidding flow:
```python
async def place_bid(posting):
    async with bid_lock_manager.with_lock(posting.marketplace_id, posting.posting_id):
        if not await should_bid(posting.posting_id, posting.marketplace_id):
            return  # Already bid
        if not posting.is_fresh():
            return  # Stale posting
        # Proceed with bid placement
```

## Files to Modify
- `src/api/models.py` - Bid model
- `src/agent_execution/market_scanner.py` - Lock manager & deduplication
- `src/agent_execution/marketplace_discovery.py` - Marketplace handlers
- `tests/test_marketplace_dedup.py` - New test file (create if not exists)

## Testing Requirements
- ✓ Test concurrent bid scenarios (2+ threads bidding on same posting)
- ✓ Test deduplication prevents duplicate bids
- ✓ Test distributed lock timeout and recovery
- ✓ Test bid withdrawal functionality
- ✓ Test posting freshness validation
- ✓ Performance: no bids on same posting within 5-minute window
- ✓ Race condition test with 100+ concurrent bids

## Acceptance Criteria
- [ ] Distributed lock prevents concurrent bids on same posting
- [ ] Deduplication check blocks duplicate bids
- [ ] Bid model extended with status/withdrawal fields
- [ ] Unique constraint enforced at database level
- [ ] All tests passing with 100% coverage
- [ ] No duplicate bids detected in 1000+ task run
- [ ] Bid withdrawal working for all marketplace types

## Timeline
Estimated: 5-6 hours

## Notes
- Financial risk: test thoroughly before merging
- Coordinate with Issue #4 (Playwright resource leak) - shared code paths
- Consider Redis for lock manager (more reliable than in-memory)
