"""
Tests for Marketplace Discovery Module

Tests for autonomous marketplace discovery, evaluation, and scoring.
"""

import pytest
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from src.agent_execution.marketplace_discovery import (
    DiscoveredMarketplace,
    DiscoveryConfig,
    MarketplaceDiscovery,
    load_marketplaces,
    save_marketplaces_config
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def temp_marketplaces_file():
    """Create a temporary marketplaces.json file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = f.name
    
    yield temp_file
    
    # Cleanup
    if os.path.exists(temp_file):
        os.remove(temp_file)


@pytest.fixture
def sample_marketplace_data():
    """Sample marketplace data for testing."""
    return {
        "version": "1.0",
        "last_updated": datetime.now().isoformat(),
        "config": {
            "search_keywords": ["freelance jobs", "remote work"],
            "min_success_rate": 0.1,
            "max_marketplaces": 20,
            "discovery_interval_hours": 168,
            "rescore_interval_hours": 24
        },
        "marketplaces": [
            {
                "name": "Upwork",
                "url": "https://upwork.com",
                "category": "freelance",
                "discovered_at": (datetime.now() - timedelta(days=7)).isoformat(),
                "last_scanned": (datetime.now() - timedelta(hours=6)).isoformat(),
                "scan_count": 10,
                "jobs_found": 50,
                "bids_placed": 5,
                "bids_won": 1,
                "total_revenue": 250.0,
                "success_rate": 0.2,
                "is_active": True,
                "priority_score": 50.0,
                "metadata": {}
            },
            {
                "name": "Fiverr",
                "url": "https://fiverr.com",
                "category": "gig",
                "discovered_at": (datetime.now() - timedelta(days=5)).isoformat(),
                "last_scanned": (datetime.now() - timedelta(days=3)).isoformat(),
                "scan_count": 5,
                "jobs_found": 30,
                "bids_placed": 2,
                "bids_won": 0,
                "total_revenue": 0.0,
                "success_rate": 0.0,
                "is_active": True,
                "priority_score": 0.0,
                "metadata": {}
            }
        ]
    }


# =============================================================================
# TESTS: DiscoveredMarketplace
# =============================================================================

class TestDiscoveredMarketplace:
    """Tests for DiscoveredMarketplace data class."""
    
    def test_create_marketplace(self):
        """Test creating a marketplace."""
        marketplace = DiscoveredMarketplace(
            name="Upwork",
            url="https://upwork.com",
            category="freelance",
            discovered_at=datetime.now()
        )
        
        assert marketplace.name == "Upwork"
        assert marketplace.url == "https://upwork.com"
        assert marketplace.category == "freelance"
        assert marketplace.scan_count == 0
        assert marketplace.is_active is True
    
    def test_marketplace_to_dict(self):
        """Test converting marketplace to dictionary."""
        now = datetime.now()
        marketplace = DiscoveredMarketplace(
            name="Upwork",
            url="https://upwork.com",
            category="freelance",
            discovered_at=now,
            bids_placed=5,
            bids_won=1,
            total_revenue=250.0
        )
        
        data = marketplace.to_dict()
        
        assert data['name'] == "Upwork"
        assert data['url'] == "https://upwork.com"
        assert data['bids_placed'] == 5
        assert data['bids_won'] == 1
        assert data['total_revenue'] == 250.0
        assert isinstance(data['discovered_at'], str)  # ISO format
    
    def test_marketplace_from_dict(self):
        """Test creating marketplace from dictionary."""
        data = {
            "name": "Upwork",
            "url": "https://upwork.com",
            "category": "freelance",
            "discovered_at": datetime.now().isoformat(),
            "last_scanned": None,
            "scan_count": 10,
            "jobs_found": 50,
            "bids_placed": 5,
            "bids_won": 1,
            "total_revenue": 250.0,
            "success_rate": 0.2,
            "is_active": True,
            "priority_score": 50.0,
            "metadata": {}
        }
        
        marketplace = DiscoveredMarketplace.from_dict(data)
        
        assert marketplace.name == "Upwork"
        assert marketplace.url == "https://upwork.com"
        assert marketplace.scan_count == 10
        assert isinstance(marketplace.discovered_at, datetime)


class TestDiscoveryConfig:
    """Tests for DiscoveryConfig data class."""
    
    def test_create_config(self):
        """Test creating a discovery config."""
        config = DiscoveryConfig(
            search_keywords=["freelance", "remote"],
            min_success_rate=0.1,
            max_marketplaces=20,
            discovery_interval_hours=168,
            rescore_interval_hours=24
        )
        
        assert len(config.search_keywords) == 2
        assert config.min_success_rate == 0.1
        assert config.max_marketplaces == 20
    
    def test_config_to_dict(self):
        """Test converting config to dictionary."""
        config = DiscoveryConfig(
            search_keywords=["freelance"],
            min_success_rate=0.15,
            max_marketplaces=25,
            discovery_interval_hours=240,
            rescore_interval_hours=48
        )
        
        data = config.to_dict()
        
        assert data['min_success_rate'] == 0.15
        assert data['max_marketplaces'] == 25


# =============================================================================
# TESTS: MarketplaceDiscovery
# =============================================================================

class TestMarketplaceDiscovery:
    """Tests for MarketplaceDiscovery class."""
    
    def test_initialize_empty(self, temp_marketplaces_file):
        """Test initializing with no existing file."""
        discovery = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        
        assert len(discovery.marketplaces) == 0
        assert discovery.config is not None
    
    def test_save_and_load_marketplaces(self, temp_marketplaces_file, sample_marketplace_data):
        """Test saving and loading marketplaces."""
        # Create discovery and add marketplaces
        discovery = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        discovery.config = DiscoveryConfig.from_dict(sample_marketplace_data['config'])
        
        for mp in sample_marketplace_data['marketplaces']:
            discovery.add_marketplace(
                name=mp['name'],
                url=mp['url'],
                category=mp['category'],
                metadata=mp.get('metadata')
            )
        
        # Save
        discovery.save_marketplaces()
        
        # Load in new instance
        discovery2 = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        
        assert len(discovery2.marketplaces) == 2
        assert discovery2.get_marketplace_by_url("https://upwork.com") is not None
        assert discovery2.get_marketplace_by_url("https://fiverr.com") is not None
    
    def test_get_active_marketplaces(self, temp_marketplaces_file):
        """Test getting active marketplaces sorted by priority."""
        discovery = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        discovery.config = DiscoveryConfig(
            search_keywords=[],
            min_success_rate=0.1,
            max_marketplaces=20,
            discovery_interval_hours=168,
            rescore_interval_hours=24
        )
        
        # Add marketplaces
        mp1 = discovery.add_marketplace("Market1", "https://market1.com", "freelance")
        mp2 = discovery.add_marketplace("Market2", "https://market2.com", "remote")
        mp3 = discovery.add_marketplace("Market3", "https://market3.com", "gig")
        
        # Set different priority scores
        mp1.priority_score = 75.0
        mp2.priority_score = 50.0
        mp3.priority_score = 25.0
        
        # Get active (should be sorted by priority descending)
        active = discovery.get_active_marketplaces()
        
        assert len(active) == 3
        assert active[0].priority_score == 75.0
        assert active[1].priority_score == 50.0
        assert active[2].priority_score == 25.0
    
    def test_get_inactive_marketplaces_excluded(self, temp_marketplaces_file):
        """Test that inactive marketplaces are excluded from active list."""
        discovery = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        discovery.config = DiscoveryConfig(
            search_keywords=[],
            min_success_rate=0.1,
            max_marketplaces=20,
            discovery_interval_hours=168,
            rescore_interval_hours=24
        )
        
        mp1 = discovery.add_marketplace("Market1", "https://market1.com", "freelance")
        mp2 = discovery.add_marketplace("Market2", "https://market2.com", "remote")
        mp2.is_active = False
        
        active = discovery.get_active_marketplaces()
        
        assert len(active) == 1
        assert active[0].name == "Market1"
    
    def test_get_marketplace_by_url(self, temp_marketplaces_file):
        """Test retrieving a marketplace by URL."""
        discovery = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        discovery.config = DiscoveryConfig(
            search_keywords=[],
            min_success_rate=0.1,
            max_marketplaces=20,
            discovery_interval_hours=168,
            rescore_interval_hours=24
        )
        
        discovery.add_marketplace("Upwork", "https://upwork.com", "freelance")
        
        mp = discovery.get_marketplace_by_url("https://upwork.com")
        
        assert mp is not None
        assert mp.name == "Upwork"
    
    def test_add_duplicate_marketplace(self, temp_marketplaces_file):
        """Test that adding a duplicate marketplace is prevented."""
        discovery = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        discovery.config = DiscoveryConfig(
            search_keywords=[],
            min_success_rate=0.1,
            max_marketplaces=20,
            discovery_interval_hours=168,
            rescore_interval_hours=24
        )
        
        discovery.add_marketplace("Upwork", "https://upwork.com", "freelance")
        discovery.add_marketplace("Upwork", "https://upwork.com", "freelance")  # Duplicate
        
        # Should only have one
        assert len(discovery.marketplaces) == 1
    
    def test_update_marketplace_stats(self, temp_marketplaces_file):
        """Test updating marketplace statistics."""
        discovery = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        discovery.config = DiscoveryConfig(
            search_keywords=[],
            min_success_rate=0.1,
            max_marketplaces=20,
            discovery_interval_hours=168,
            rescore_interval_hours=24
        )
        
        discovery.add_marketplace("Upwork", "https://upwork.com", "freelance")
        
        # Update stats
        discovery.update_marketplace_stats(
            "https://upwork.com",
            jobs_found=10,
            bid_placed=True,
            bid_won=True,
            revenue=250.0
        )
        
        mp = discovery.get_marketplace_by_url("https://upwork.com")
        
        assert mp.jobs_found == 10
        assert mp.bids_placed == 1
        assert mp.bids_won == 1
        assert mp.total_revenue == 250.0
        assert mp.success_rate == 1.0
        assert mp.last_scanned is not None
    
    def test_calculate_priority_score(self, temp_marketplaces_file):
        """Test priority score calculation."""
        discovery = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        discovery.config = DiscoveryConfig(
            search_keywords=[],
            min_success_rate=0.1,
            max_marketplaces=20,
            discovery_interval_hours=168,
            rescore_interval_hours=24
        )
        
        mp1 = discovery.add_marketplace("Market1", "https://market1.com", "freelance")
        mp2 = discovery.add_marketplace("Market2", "https://market2.com", "remote")
        
        # Market 1: high success rate, high revenue
        mp1.success_rate = 0.8
        mp1.total_revenue = 1000.0
        mp1.last_scanned = datetime.now() - timedelta(hours=6)  # Recently scanned
        
        # Market 2: lower success rate, lower revenue
        mp2.success_rate = 0.3
        mp2.total_revenue = 200.0
        mp2.last_scanned = datetime.now() - timedelta(days=10)  # Stale scan
        
        # Recalculate scores
        discovery.rescore_all_marketplaces()
        
        # Market 1 should have higher priority
        assert mp1.priority_score > mp2.priority_score
    
    def test_rescore_all_marketplaces(self, temp_marketplaces_file):
        """Test rescoring all marketplaces."""
        discovery = MarketplaceDiscovery(config_file=temp_marketplaces_file)
        discovery.config = DiscoveryConfig(
            search_keywords=[],
            min_success_rate=0.1,
            max_marketplaces=20,
            discovery_interval_hours=168,
            rescore_interval_hours=24
        )
        
        mp1 = discovery.add_marketplace("Market1", "https://market1.com", "freelance")
        mp2 = discovery.add_marketplace("Market2", "https://market2.com", "remote")
        
        # Set initial scores
        mp1.priority_score = 0.0
        mp2.priority_score = 0.0
        
        # Update and rescore
        mp1.success_rate = 0.5
        mp2.success_rate = 0.3
        discovery.rescore_all_marketplaces()
        
        # Scores should be non-zero and different
        assert mp1.priority_score > 0
        assert mp2.priority_score >= 0
        assert mp1.priority_score > mp2.priority_score


# =============================================================================
# TESTS: Helper Functions
# =============================================================================

class TestHelperFunctions:
    """Tests for module-level helper functions."""
    
    def test_load_marketplaces(self, temp_marketplaces_file, sample_marketplace_data):
        """Test load_marketplaces helper function."""
        # Write sample data to file
        with open(temp_marketplaces_file, 'w') as f:
            json.dump(sample_marketplace_data, f)
        
        # Load
        marketplaces = load_marketplaces(config_file=temp_marketplaces_file)
        
        assert len(marketplaces) == 2
        assert marketplaces[0].name in ["Upwork", "Fiverr"]
    
    def test_save_marketplaces_config(self, temp_marketplaces_file):
        """Test save_marketplaces_config helper function."""
        mp1 = DiscoveredMarketplace(
            name="Upwork",
            url="https://upwork.com",
            category="freelance",
            discovered_at=datetime.now()
        )
        
        save_marketplaces_config([mp1], config_file=temp_marketplaces_file)
        
        # Verify saved
        with open(temp_marketplaces_file, 'r') as f:
            data = json.load(f)
        
        assert len(data['marketplaces']) == 1
        assert data['marketplaces'][0]['name'] == "Upwork"


# =============================================================================
# TESTS: JSON Serialization Round-trip
# =============================================================================

class TestJSONRoundtrip:
    """Tests for JSON serialization and deserialization."""
    
    def test_marketplace_json_roundtrip(self, temp_marketplaces_file):
        """Test that marketplace data survives JSON round-trip."""
        original = DiscoveredMarketplace(
            name="Upwork",
            url="https://upwork.com",
            category="freelance",
            discovered_at=datetime.now(),
            scan_count=10,
            jobs_found=50,
            bids_placed=5,
            bids_won=1,
            total_revenue=250.0,
            success_rate=0.2,
            is_active=True,
            priority_score=50.0
        )
        
        # Convert to dict and back
        data = original.to_dict()
        restored = DiscoveredMarketplace.from_dict(data)
        
        assert restored.name == original.name
        assert restored.url == original.url
        assert restored.scan_count == original.scan_count
        assert restored.bids_won == original.bids_won
        assert restored.total_revenue == original.total_revenue
        assert isinstance(restored.discovered_at, datetime)
