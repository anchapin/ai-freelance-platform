"""
Tests for Virtual Wallet Module (Issues #92, #93)
"""

from datetime import datetime
import pytest
from src.api.database import SessionLocal
from src.api.models import VirtualWallet
from src.agent_execution.virtual_wallet import (
    VirtualWalletManager,
    get_virtual_wallet,
    reset_virtual_wallet,
)
from src.config.config_manager import reset_instance


@pytest.fixture(autouse=True)
def reset_config():
    """Reset config before each test."""
    reset_instance()
    reset_virtual_wallet()
    yield


@pytest.fixture
def db_session():
    """Provide a database session for tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def wallet_manager():
    """Provide a virtual wallet manager instance."""
    manager = VirtualWalletManager()
    return manager


class TestVirtualWalletManager:
    """Test suite for Virtual Wallet Manager."""

    def test_initialization(self, wallet_manager):
        """Test that wallet manager initializes correctly."""
        assert wallet_manager is not None
        assert wallet_manager.wallet_id == "default"
        assert wallet_manager._wallet is not None

    def test_create_default_wallet(self, db_session):
        """Test creating a default wallet."""
        # Clear any existing wallet
        db_session.query(VirtualWallet).delete()
        db_session.commit()

        # Create new wallet manager (will create default wallet)
        manager = VirtualWalletManager()

        assert manager._wallet is not None
        assert manager._wallet.balance_cents > 0
        assert manager._wallet.budget_cap_cents > 0

    def test_deduct_success(self, wallet_manager, db_session):
        """Test successful cost deduction."""
        initial_balance = wallet_manager._wallet.balance_cents
        initial_budget_spent = wallet_manager._wallet.budget_spent_cents

        # Deduct $10 (1000 cents)
        success = wallet_manager.deduct("llm", 1000)

        assert success is True
        assert wallet_manager._wallet.balance_cents == initial_balance - 1000
        assert wallet_manager._wallet.budget_spent_cents == initial_budget_spent + 1000

    def test_deduct_over_budget(self, wallet_manager, db_session):
        """Test deduction when over budget."""
        # Set budget to $1 (100 cents)
        wallet_manager.set_budget_cap(100)

        # Try to deduct $10 (1000 cents) - should fail
        success = wallet_manager.deduct("llm", 1000)

        assert success is False

    def test_add_revenue(self, wallet_manager):
        """Test adding revenue to wallet."""
        initial_balance = wallet_manager._wallet.balance_cents
        initial_earned = wallet_manager._wallet.total_earned_cents

        # Add $50 (5000 cents)
        success = wallet_manager.add_revenue(5000)

        assert success is True
        assert wallet_manager._wallet.balance_cents == initial_balance + 5000
        assert wallet_manager._wallet.total_earned_cents == initial_earned + 5000

    def test_get_available_budget(self, wallet_manager):
        """Test getting available budget."""
        budget_info = wallet_manager.get_available_budget()

        assert "budget_cap_cents" in budget_info
        assert "budget_spent_cents" in budget_info
        assert "budget_remaining_cents" in budget_info
        assert "budget_percentage_used" in budget_info

    def test_get_wallet_status(self, wallet_manager):
        """Test getting complete wallet status."""
        status = wallet_manager.get_wallet_status()

        assert "balance_dollars" in status
        assert "total_spent_dollars" in status
        assert "total_earned_dollars" in status
        assert "budget_cap_dollars" in status
        assert "budget_remaining_dollars" in status

    def test_add_seed_money(self, wallet_manager):
        """Test adding seed money."""
        initial_balance = wallet_manager._wallet.balance_cents

        # Add $100 (10000 cents)
        success = wallet_manager.add_seed_money(10000)

        assert success is True
        assert wallet_manager._wallet.balance_cents == initial_balance + 10000

    def test_set_budget_cap(self, wallet_manager):
        """Test setting budget cap."""
        # Set new budget cap to $200 (20000 cents)
        success = wallet_manager.set_budget_cap(20000, "weekly")

        assert success is True
        assert wallet_manager._wallet.budget_cap_cents == 20000
        assert wallet_manager._wallet.budget_reset_period == "weekly"

    def test_budget_reset(self, wallet_manager):
        """Test automatic budget reset."""
        # Set budget cap and reset period
        wallet_manager.set_budget_cap(10000, "daily")

        # Spend some budget
        wallet_manager.deduct("test", 5000)

        # Budget should be reset when period elapses
        # (In real scenario, this happens on next operation)

    def test_singleton_instance(self):
        """Test that get_virtual_wallet returns singleton."""
        wallet1 = get_virtual_wallet()
        wallet2 = get_virtual_wallet()

        assert wallet1 is wallet2


class TestVirtualWalletModel:
    """Test suite for VirtualWallet database model."""

    def test_virtual_wallet_creation(self, db_session):
        """Test creating a VirtualWallet record."""
        wallet = VirtualWallet(
            id="test-wallet-1",
            balance_cents=10000,
            total_spent_cents=5000,
            total_earned_cents=20000,
            budget_cap_cents=50000,
            budget_reset_period="weekly",
            budget_start_at=datetime.utcnow(),
            budget_spent_cents=10000,
            low_budget_threshold_percent=25,
            critical_budget_threshold_percent=10,
        )

        db_session.add(wallet)
        db_session.commit()

        # Verify it was saved
        saved_wallet = (
            db_session.query(VirtualWallet).filter_by(id="test-wallet-1").first()
        )
        assert saved_wallet is not None
        assert saved_wallet.balance_cents == 10000
        assert saved_wallet.budget_cap_cents == 50000

    def test_virtual_wallet_to_dict(self):
        """Test to_dict method of VirtualWallet."""
        wallet = VirtualWallet(
            id="test-wallet-2",
            balance_cents=10000,
            budget_cap_cents=50000,
            budget_spent_cents=10000,
            budget_reset_period="weekly",
        )

        wallet_dict = wallet.to_dict()

        assert "id" in wallet_dict
        assert "balance_dollars" in wallet_dict
        assert wallet_dict["balance_dollars"] == 100.0
        assert "budget_remaining_dollars" in wallet_dict
        assert wallet_dict["budget_remaining_dollars"] == 400.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
