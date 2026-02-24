# Marketplace Discovery - Quick Start Guide

## What Changed?

The system now **automatically manages and optimizes** which freelance marketplaces to scan, instead of using a single hardcoded URL.

## Key Files

| File | Purpose |
|------|---------|
| `src/agent_execution/marketplace_discovery.py` | Core discovery system |
| `src/agent_execution/market_scanner.py` | Updated to use discovery system |
| `data/marketplaces.json` | Configuration and performance tracking |
| `tests/test_marketplace_discovery.py` | Test suite (17 tests) |

## How It Works

### 1. Configuration Storage (`data/marketplaces.json`)

Stores all discovered marketplaces with metrics:

```json
{
  "marketplaces": [
    {
      "name": "Upwork",
      "url": "https://upwork.com/jobs/",
      "category": "freelance",
      "bids_placed": 5,
      "bids_won": 1,
      "total_revenue": 250.0,
      "success_rate": 0.2,          // (bids_won / bids_placed)
      "priority_score": 50.0,       // Profitability ranking
      "is_active": true
    }
  ]
}
```

### 2. Automatic Ranking

Marketplaces are ranked by **priority score**:

```
Priority Score = (Success Rate × 0.5 + Revenue Ratio × 0.5) × Activity Factor × 100
```

- **Recency Boost**: Recently scanned marketplaces get 1.5x boost
- **Staleness Penalty**: Marketplaces not scanned in 7+ days get 0.7x penalty
- **Results**: Highest-ROI marketplaces are scanned first

### 3. Integration with Market Scanner

**Before**: Scanned single hardcoded URL
```python
scanner = MarketScanner(marketplace_url="https://example.com")
```

**After**: Scans all configured marketplaces
```python
async with MarketScanner() as scanner:
    result = await scanner.scan_all_marketplaces()
    # Automatically loads URLs from config
    # Scans all active marketplaces
    # Deduplicates jobs
```

## Common Tasks

### View Active Marketplaces

```python
from src.agent_execution.marketplace_discovery import MarketplaceDiscovery

discovery = MarketplaceDiscovery()
active = discovery.get_active_marketplaces()

for mp in active:
    print(f"{mp.name}: {mp.priority_score:.1f} (success: {mp.success_rate:.1%})")
```

### Record a Bid Result

```python
discovery.update_marketplace_stats(
    url="https://upwork.com/jobs/",
    jobs_found=15,      # Found 15 jobs in this scan
    bid_placed=True,    # Placed a bid
    bid_won=True,       # Won the bid!
    revenue=250.0       # Revenue from winning bid
)
discovery.save_marketplaces()  # Persist changes
```

### Add a New Marketplace

```python
marketplace = discovery.add_marketplace(
    name="NewPlatform",
    url="https://newplatform.com",
    category="freelance",
    metadata={"description": "New discovery"}
)
discovery.save_marketplaces()
```

### Rescore All Marketplaces

```python
discovery.rescore_all_marketplaces()
discovery.save_marketplaces()
```

## Environment Variables

### New Setting
```bash
MARKETPLACES_FILE=data/marketplaces.json
```

### Deprecated (but still supported)
```bash
MARKETPLACE_URL=https://example.com  # Legacy - takes priority if set
```

## Testing

Run the test suite:

```bash
pytest tests/test_marketplace_discovery.py -v
```

Current status: **17/17 tests passing** ✓

## Migration Path

### For Existing Deployments

1. **No action required** - System is backward compatible
2. Optional: Set `MARKETPLACES_FILE` in `.env`
3. Current `MARKETPLACE_URL` still works but is deprecated
4. Recommended: Use new JSON-based configuration

### Configuration Update Steps

1. Edit `data/marketplaces.json`
2. Add your target marketplaces to the list
3. Set `is_active: true` for marketplaces to scan
4. Restart the scanner

Example:

```json
{
  "name": "MyTargetMarketplace",
  "url": "https://mymarketplace.com",
  "category": "freelance",
  "discovered_at": "2024-02-24T00:00:00",
  "is_active": true
}
```

## Performance Insights

The system tracks important metrics:

- **Scan Count**: How many times this marketplace has been scanned
- **Jobs Found**: Total jobs discovered across all scans
- **Bids Placed**: Total bids submitted
- **Success Rate**: Percentage of bids that won
- **Total Revenue**: Cumulative earnings from this marketplace

### Example Performance Tracking

```python
mp = discovery.get_marketplace_by_url("https://upwork.com/jobs/")

print(f"Marketplace: {mp.name}")
print(f"  Scans: {mp.scan_count}")
print(f"  Jobs: {mp.jobs_found}")
print(f"  Bids: {mp.bids_placed}/{mp.bids_won} won")
print(f"  Revenue: ${mp.total_revenue:.2f}")
print(f"  ROI Score: {mp.priority_score:.1f}")
```

## Architecture

```
MarketScanner (loads URLs from config)
        ↓
MarketplaceDiscovery (manages & scores)
        ↓
data/marketplaces.json (persistent storage)
```

## Future Features

- **Web Search Integration**: Auto-discover new marketplaces
- **Quality Evaluation**: Playwright-based marketplace assessment
- **Smart Deactivation**: Automatically remove low-performing marketplaces
- **Category Optimization**: Different strategies per task type
- **Analytics Dashboard**: Real-time performance visualization

## Troubleshooting

### Q: MarketScanner not loading marketplaces?
A: Ensure `data/marketplaces.json` exists with valid JSON and `is_active: true` entries.

### Q: Priority scores all zero?
A: Normal for newly added marketplaces. Scores update after bidding activity.

### Q: Want to use old single-URL method?
A: Set `MARKETPLACE_URL` env var - still supported for backward compatibility.

### Q: How to reset scores?
A: Edit `data/marketplaces.json` and set metrics to 0, or use:
```python
discovery = MarketplaceDiscovery()
for mp in discovery.marketplaces:
    mp.bids_placed = 0
    mp.bids_won = 0
    mp.total_revenue = 0.0
discovery.rescore_all_marketplaces()
discovery.save_marketplaces()
```

## Support

- Implementation Details: See `MARKETPLACE_DISCOVERY_IMPLEMENTATION.md`
- Test Examples: See `tests/test_marketplace_discovery.py`
- Source Code: See `src/agent_execution/marketplace_discovery.py`
