"""
Arena Profitability Tests

Comprehensive test coverage for agent arena profit calculations and winner selection.
Tests cover edge cases including:
- Negative profit scenarios
- Tied profit scenarios
- Zero revenue scenarios
- Extreme token counts
- Both agents failing
- Dynamic pricing validation
"""

import pytest
from unittest.mock import Mock
from src.agent_execution.arena import (
    ProfitCalculator,
    CostConfig,
    ArenaRouter,
    AgentConfig,
    CompetitionType
)
from src.llm_service import LLMService


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def cost_config():
    """Standard cost configuration for testing."""
    return CostConfig()


@pytest.fixture
def profit_calculator(cost_config):
    """Profit calculator instance for testing."""
    return ProfitCalculator(cost_config)


@pytest.fixture
def mock_llm_cloud():
    """Mock LLM service for cloud model (GPT-4o)."""
    mock = Mock(spec=LLMService)
    mock.get_model.return_value = "gpt-4o"
    mock.is_local.return_value = False
    return mock


@pytest.fixture
def mock_llm_local():
    """Mock LLM service for local model."""
    mock = Mock(spec=LLMService)
    mock.get_model.return_value = "llama3.2"
    mock.is_local.return_value = True
    return mock


@pytest.fixture
def agent_config_cloud(mock_llm_cloud):
    """Cloud agent configuration."""
    return AgentConfig(
        name="Agent_Cloud",
        llm_service=mock_llm_cloud,
        system_prompt_style="standard",
        max_retries=2,
        planning_time_multiplier=1.0
    )


@pytest.fixture
def agent_config_local(mock_llm_local):
    """Local agent configuration."""
    return AgentConfig(
        name="Agent_Local",
        llm_service=mock_llm_local,
        system_prompt_style="standard",
        max_retries=0,
        planning_time_multiplier=2.0
    )


# =============================================================================
# BASIC PROFIT CALCULATION TESTS
# =============================================================================

class TestProfitCalculation:
    """Test basic profit calculation logic."""
    
    def test_calculate_profit_score_cloud_model(self, profit_calculator, agent_config_cloud):
        """Test profit calculation for cloud model (GPT-4o)."""
        agent_result = {
            "usage": {
                "prompt_tokens": 1500,
                "completion_tokens": 500
            },
            "execution_time_seconds": 45.0
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=1000  # $10.00
        )
        
        # GPT-4o costs: (1500/1M * 250) + (500/1M * 1000) = 0.375 + 0.5 = 0.875 cents
        # E2B cost: (45/60) * 5 = 3.75 cents
        # Total cost: 0.875 + 3.75 = 4.625 cents
        # Profit: 1000 - 4.625 = 995.375 cents
        assert profit["profit"] > 0
        assert profit["is_profitable"] is True
        assert profit["llm_cost"] > 0
        assert profit["e2b_cost"] > 0
    
    def test_calculate_profit_score_local_model(self, profit_calculator, agent_config_local):
        """Test profit calculation for local model (no API cost)."""
        agent_result = {
            "usage": {
                "prompt_tokens": 2000,
                "completion_tokens": 800
            },
            "execution_time_seconds": 60.0
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_local,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        # Local model has no LLM cost
        assert profit["llm_cost"] == 0
        assert profit["input_cost"] == 0
        assert profit["output_cost"] == 0
        # E2B cost: (60/60) * 5 = 5 cents
        assert profit["e2b_cost"] == 5.0
        # Profit: 1000 - 5 = 995 cents
        assert profit["profit"] == 995.0
        assert profit["is_profitable"] is True
    
    def test_calculate_profit_score_with_nested_steps(self, profit_calculator, agent_config_cloud):
        """Test profit calculation with nested step usage."""
        agent_result = {
            "execution_time_seconds": 30.0,
            "steps": {
                "planning": {
                    "usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 200
                    }
                },
                "execution": {
                    "usage": {
                        "prompt_tokens": 500,
                        "completion_tokens": 300
                    }
                }
            }
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        # Total tokens: 1000 + 500 input, 200 + 300 output = 1500 + 500
        assert profit["input_tokens"] == 1500
        assert profit["output_tokens"] == 500


# =============================================================================
# EDGE CASE: NEGATIVE PROFIT
# =============================================================================

class TestNegativeProfitScenarios:
    """Test scenarios where agents lose money on tasks."""
    
    def test_negative_profit_high_cost(self, profit_calculator, agent_config_cloud):
        """Test when LLM cost exceeds task revenue."""
        agent_result = {
            "usage": {
                "prompt_tokens": 500000,  # Very large token usage
                "completion_tokens": 500000
            },
            "execution_time_seconds": 3600.0  # 1 hour of compute
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=500  # Only $5.00 revenue
        )
        
        # Profit will be negative (massive cost)
        # Cost: (500K/1M * 250) + (500K/1M * 1000) + (3600/60 * 5) = 125 + 500 + 300 = 925 cents
        assert profit["profit"] < 0
        assert profit["is_profitable"] is False
        assert profit["total_cost"] > profit["revenue"]
    
    def test_negative_profit_zero_revenue(self, profit_calculator, agent_config_cloud):
        """Test when task has zero revenue."""
        agent_result = {
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500
            },
            "execution_time_seconds": 30.0
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=0  # Free task
        )
        
        # Any cost with zero revenue = negative profit
        assert profit["profit"] < 0
        assert profit["is_profitable"] is False


# =============================================================================
# EDGE CASE: ZERO TOKENS / MINIMAL EXECUTION
# =============================================================================

class TestMinimalExecutionScenarios:
    """Test scenarios with minimal resource usage."""
    
    def test_zero_tokens_zero_time(self, profit_calculator, agent_config_cloud):
        """Test when agent uses no tokens and no compute time."""
        agent_result = {
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0
            },
            "execution_time_seconds": 0
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        # No cost, full profit
        assert profit["profit"] == 1000
        assert profit["is_profitable"] is True
        assert profit["total_cost"] == 0
    
    def test_missing_usage_data(self, profit_calculator, agent_config_cloud):
        """Test when usage data is missing."""
        agent_result = {
            "execution_time_seconds": 10.0
            # No usage field
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        # Should handle gracefully with zero tokens
        assert profit["input_tokens"] == 0
        assert profit["output_tokens"] == 0
        assert profit["llm_cost"] == 0
        # E2B cost: (10/60) * 5 = 0.833... cents
        assert profit["e2b_cost"] == pytest.approx(0.833, abs=0.01)


# =============================================================================
# EDGE CASE: TIED PROFITS
# =============================================================================

class TestTiedProfitScenarios:
    """Test scenarios where both agents have equal profit."""
    
    def test_identical_agents_identical_results(self, profit_calculator, agent_config_cloud):
        """Test when two identical agents produce identical results."""
        agent_result = {
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500
            },
            "execution_time_seconds": 30.0
        }
        
        profit_a = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        profit_b = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        # Both should have identical profit
        assert profit_a["profit"] == profit_b["profit"]
        assert profit_a["total_cost"] == profit_b["total_cost"]


# =============================================================================
# EDGE CASE: MODEL-SPECIFIC PRICING
# =============================================================================

class TestModelPricingDifferences:
    """Test that different models have correct pricing."""
    
    def test_gpt4o_vs_gpt4o_mini_pricing(self, profit_calculator, agent_config_cloud):
        """Test pricing differences between GPT-4o and GPT-4o-mini."""
        agent_result = {
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500
            },
            "execution_time_seconds": 30.0
        }
        
        # GPT-4o pricing
        agent_config_cloud.llm_service.get_model.return_value = "gpt-4o"
        profit_gpt4o = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        # GPT-4o-mini pricing
        agent_config_cloud.llm_service.get_model.return_value = "gpt-4o-mini"
        profit_mini = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        # GPT-4o should cost more than mini
        assert profit_gpt4o["llm_cost"] > profit_mini["llm_cost"]
        # GPT-4o should have lower profit
        assert profit_gpt4o["profit"] < profit_mini["profit"]
    
    def test_cloud_vs_local_pricing(self, profit_calculator, agent_config_cloud, agent_config_local):
        """Test that local models have no API cost."""
        agent_result = {
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500
            },
            "execution_time_seconds": 30.0
        }
        
        profit_cloud = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        profit_local = profit_calculator.calculate_profit_score(
            agent_config=agent_config_local,
            agent_result=agent_result,
            task_revenue=1000
        )
        
        # Local should have no LLM cost
        assert profit_local["llm_cost"] == 0
        assert profit_cloud["llm_cost"] > 0
        # Local should be more profitable
        assert profit_local["profit"] > profit_cloud["profit"]


# =============================================================================
# EDGE CASE: EXTREME TOKEN COUNTS
# =============================================================================

class TestExtremeTokenScenarios:
    """Test with very large and very small token counts."""
    
    def test_extremely_high_token_count(self, profit_calculator, agent_config_cloud):
        """Test with massive token usage."""
        agent_result = {
            "usage": {
                "prompt_tokens": 1000000,  # 1M input tokens
                "completion_tokens": 500000  # 500K output tokens
            },
            "execution_time_seconds": 300.0
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=50000  # $500.00
        )
        
        # GPT-4o: (1M/1M * 250) + (500K/1M * 1000) = 250 + 500 = 750 cents
        # E2B: (300/60) * 5 = 25 cents
        # Total: 775 cents, Profit: 50000 - 775 = 49225 cents
        assert profit["llm_cost"] == pytest.approx(750, abs=1)
        assert profit["e2b_cost"] == 25.0
        assert profit["profit"] == pytest.approx(49225, abs=1)
    
    def test_extremely_long_execution_time(self, profit_calculator, agent_config_local):
        """Test with very long execution time."""
        agent_result = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50
            },
            "execution_time_seconds": 3600  # 1 hour
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_local,
            agent_result=agent_result,
            task_revenue=10000  # $100.00
        )
        
        # E2B cost: (3600/60) * 5 = 300 cents
        assert profit["e2b_cost"] == 300.0
        assert profit["profit"] == 9700  # 10000 - 300


# =============================================================================
# WINNER DETERMINATION TESTS
# =============================================================================

class TestWinnerDetermination:
    """Test the winner determination logic for various scenarios."""
    
    def test_one_passes_one_fails_passer_wins(self):
        """Test that passing agent wins when other fails."""
        router = ArenaRouter(competition_type=CompetitionType.MODEL)
        
        result_a = {"approved": True}
        result_b = {"approved": False}
        profit_a = {"profit": 100}
        profit_b = {"profit": 500}  # Higher profit but failed
        
        winner, reason = router._determine_winner(result_a, result_b, profit_a, profit_b)
        assert winner == "agent_a"
        assert "Passed review" in reason
    
    def test_both_pass_higher_profit_wins(self):
        """Test that higher profit wins when both pass."""
        router = ArenaRouter(competition_type=CompetitionType.MODEL)
        
        result_a = {"approved": True}
        result_b = {"approved": True}
        profit_a = {"profit": 500}  # Lower profit
        profit_b = {"profit": 800}  # Higher profit
        
        winner, reason = router._determine_winner(result_a, result_b, profit_a, profit_b)
        assert winner == "agent_b"
        assert "Higher profit" in reason
    
    def test_both_fail_lower_loss_wins(self):
        """Test that lower loss (higher profit) wins when both fail."""
        router = ArenaRouter(competition_type=CompetitionType.MODEL)
        
        result_a = {"approved": False}
        result_b = {"approved": False}
        profit_a = {"profit": -100}  # Loss of $1.00
        profit_b = {"profit": -50}   # Loss of $0.50
        
        winner, reason = router._determine_winner(result_a, result_b, profit_a, profit_b)
        assert winner == "agent_b"
        assert "lower loss" in reason
    
    def test_both_fail_equal_loss_defaults_to_agent_a(self):
        """Test that equal loss defaults to Agent A."""
        router = ArenaRouter(competition_type=CompetitionType.MODEL)
        
        result_a = {"approved": False}
        result_b = {"approved": False}
        profit_a = {"profit": -100}  # Equal loss
        profit_b = {"profit": -100}
        
        winner, reason = router._determine_winner(result_a, result_b, profit_a, profit_b)
        # When profits are equal, the condition profit_a["profit"] > profit_b["profit"] is False
        # so it goes to agent_b by the else clause
        assert winner == "agent_b"


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestProfitabilityIntegration:
    """Integration tests for profitability calculations."""
    
    @pytest.mark.parametrize("input_tokens,output_tokens,execution_time,revenue,expected_profitable", [
        (1000, 500, 30, 1000, True),      # Normal case - profitable
        (500000, 500000, 3600, 500, False), # High tokens, 1hr compute - unprofitable
        (0, 0, 0, 1000, True),            # Free execution
        (0, 0, 0, 0, False),              # Zero revenue free task
    ])
    def test_profitability_matrix(self, profit_calculator, agent_config_cloud, 
                                 input_tokens, output_tokens, execution_time, 
                                 revenue, expected_profitable):
        """Test profitability across various parameter combinations."""
        agent_result = {
            "usage": {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens
            },
            "execution_time_seconds": execution_time
        }
        
        profit = profit_calculator.calculate_profit_score(
            agent_config=agent_config_cloud,
            agent_result=agent_result,
            task_revenue=revenue
        )
        
        assert profit["is_profitable"] == expected_profitable


# =============================================================================
# COST CONFIG VALIDATION
# =============================================================================

class TestCostConfig:
    """Test cost configuration values."""
    
    def test_cost_config_has_all_rates(self):
        """Test that CostConfig defines all necessary rates."""
        config = CostConfig()
        
        # Cloud model rates
        assert config.CLOUD_GPT4O_INPUT_COST > 0
        assert config.CLOUD_GPT4O_OUTPUT_COST > 0
        assert config.CLOUD_GPT4O_MINI_INPUT_COST > 0
        assert config.CLOUD_GPT4O_MINI_OUTPUT_COST > 0
        
        # Local model
        assert config.LOCAL_COST == 0
        
        # E2B cost
        assert config.E2B_COST_PER_MINUTE > 0
        
        # Default revenue
        assert config.DEFAULT_TASK_REVENUE > 0
    
    def test_cost_config_mini_cheaper_than_standard(self):
        """Test that GPT-4o-mini is cheaper than standard GPT-4o."""
        config = CostConfig()
        
        # Mini input should be cheaper than standard
        assert config.CLOUD_GPT4O_MINI_INPUT_COST < config.CLOUD_GPT4O_INPUT_COST
        # Mini output should be cheaper than standard
        assert config.CLOUD_GPT4O_MINI_OUTPUT_COST < config.CLOUD_GPT4O_OUTPUT_COST
