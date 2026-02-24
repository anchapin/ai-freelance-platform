"""
Unit tests for ProfitCalculator.calculate_profit_score.

This module tests the profit calculation for arena agents:
Profit = Task Revenue - (LLM Cost + E2B Compute Cost)

Critical: Errors in this calculation can lead to incorrect agent routing
and financial losses.
"""

import pytest
import sys
import os
from unittest.mock import Mock

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.agent_execution.arena import ProfitCalculator, CostConfig, AgentConfig


class TestProfitCalculator:
    """Test suite for ProfitCalculator class."""
    
    # =============================================================================
    # COST CONFIGURATION TESTS
    # =============================================================================
    
    def test_default_cost_config(self):
        """Test default cost configuration."""
        config = CostConfig()
        
        # Check LLM costs (in cents per 1M tokens)
        assert config.CLOUD_GPT4O_INPUT_COST == 250  # $2.50/1M
        assert config.CLOUD_GPT4O_OUTPUT_COST == 1000  # $10.00/1M
        assert config.CLOUD_GPT4O_MINI_INPUT_COST == 15  # $0.15/1M
        assert config.CLOUD_GPT4O_MINI_OUTPUT_COST == 60  # $0.60/1M
        assert config.LOCAL_COST == 0  # Local models cost nothing
        
        # Check E2B costs (per minute)
        assert config.E2B_COST_PER_MINUTE == 5  # $0.05/min
        
        # Check default task revenue
        assert config.DEFAULT_TASK_REVENUE == 500  # $5.00
    
    # =============================================================================
    # GPT-4O PROFIT CALCULATION TESTS
    # =============================================================================
    
    def test_gpt4o_profit_calculation(self):
        """Test profit calculation for GPT-4o cloud model."""
        config = CostConfig()
        calculator = ProfitCalculator(config)
        
        # Create mock agent config
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(
            name="TestAgent",
            llm_service=mock_llm,
            system_prompt_style="standard",
            max_retries=2
        )
        
        # Create mock result with token usage
        agent_result = {
            "usage": {
                "prompt_tokens": 1000000,  # 1M input tokens
                "completion_tokens": 1000000  # 1M output tokens
            },
            "execution_time_seconds": 60  # 1 minute
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=500  # $5.00
        )
        
        # Verify structure
        assert "profit" in result
        assert "revenue" in result
        assert "llm_cost" in result
        assert "e2b_cost" in result
        assert "total_cost" in result
        assert "input_tokens" in result
        assert "output_tokens" in result
        assert "is_profitable" in result
        
        # Verify calculations (in cents)
        # LLM Cost: 1M input @ $2.50/1M + 1M output @ $10.00/1M = $12.50 = 1250 cents
        assert result["llm_cost"] == 1250
        # E2B Cost: 1 min @ $0.05/min = $0.05 = 5 cents
        assert result["e2b_cost"] == 5
        # Total Cost: 1250 + 5 = 1255 cents
        assert result["total_cost"] == 1255
        # Profit: 500 - 1255 = -755 cents (loss)
        assert result["profit"] == -755
        assert result["is_profitable"] is False
    
    def test_gpt4o_profit_small_usage(self):
        """Test profit calculation for GPT-4o with small token usage."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(
            name="TestAgent",
            llm_service=mock_llm
        )
        
        # Small usage: 1000 input + 500 output tokens
        agent_result = {
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500
            },
            "execution_time_seconds": 30  # 0.5 minutes
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=500  # $5.00
        )
        
        # Input: 1000/1M * $2.50 = $0.0025 = 0.25 cents
        # Output: 500/1M * $10.00 = $0.005 = 0.5 cents
        # E2B: 0.5 * $0.05 = $0.025 = 2.5 cents
        # Total: ~3 cents
        assert result["llm_cost"] < 10  # Less than 10 cents
        assert result["e2b_cost"] == 2.5  # Actual value
        assert result["input_tokens"] == 1000
        assert result["output_tokens"] == 500
    
    # =============================================================================
    # GPT-4O-MINI PROFIT CALCULATION TESTS
    # =============================================================================
    
    def test_gpt4o_mini_profit_calculation(self):
        """Test profit calculation for GPT-4o-mini."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o-mini"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(
            name="TestAgent",
            llm_service=mock_llm
        )
        
        agent_result = {
            "usage": {
                "prompt_tokens": 1000000,  # 1M tokens
                "completion_tokens": 500000  # 500K tokens
            },
            "execution_time_seconds": 60
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=500
        )
        
        # Input: 1M * $0.15/1M = $0.15 = 15 cents
        # Output: 500K * $0.60/1M = $0.30 = 30 cents
        # E2B: 1 min * $0.05/min = 5 cents
        # Total: 50 cents
        assert result["llm_cost"] == 45  # 15 + 30
        assert result["e2b_cost"] == 5
        assert result["total_cost"] == 50
    
    # =============================================================================
    # LOCAL MODEL PROFIT CALCULATION TESTS
    # =============================================================================
    
    def test_local_model_zero_llm_cost(self):
        """Test that local models have zero LLM cost."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "llama3.2"
        mock_llm.is_local.return_value = True
        
        agent_config = AgentConfig(
            name="LocalAgent",
            llm_service=mock_llm
        )
        
        agent_result = {
            "usage": {
                "prompt_tokens": 1000000,
                "completion_tokens": 1000000
            },
            "execution_time_seconds": 120  # 2 minutes
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=500
        )
        
        # Local model should have zero LLM cost
        assert result["llm_cost"] == 0
        # But still pays E2B compute
        assert result["e2b_cost"] == 10  # 2 min * $0.05 = 10 cents
        # Total cost = E2B only
        assert result["total_cost"] == 10
        # Profit = 500 - 10 = 490 cents ($4.90)
        assert result["profit"] == 490
        assert result["is_profitable"] is True
    
    def test_local_model_profitable(self):
        """Test local model generates profit."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "llama3.2"
        mock_llm.is_local.return_value = True
        
        agent_config = AgentConfig(
            name="LocalAgent",
            llm_service=mock_llm
        )
        
        # Standard usage
        agent_result = {
            "usage": {
                "prompt_tokens": 5000,
                "completion_tokens": 2000
            },
            "execution_time_seconds": 60
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=500
        )
        
        assert result["llm_cost"] == 0
        assert result["e2b_cost"] == 5
        assert result["profit"] == 495  # 500 - 5
        assert result["is_profitable"] is True
    
    # =============================================================================
    # E2B COST CALCULATION TESTS
    # =============================================================================
    
    def test_e2b_cost_calculation(self):
        """Test E2B cost calculation based on execution time."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o-mini"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(
            name="TestAgent",
            llm_service=mock_llm
        )
        
        # Test different execution times (E2B cost = execution_time/60 * 5 cents)
        test_cases = [
            (30, 2.5),   # 0.5 min * 5 = 2.5 cents
            (60, 5),      # 1 min * 5 = 5 cents
            (120, 10),    # 2 min * 5 = 10 cents
            (300, 25),    # 5 min * 5 = 25 cents
            (600, 50),    # 10 min * 5 = 50 cents
        ]
        
        for exec_time, expected_cost in test_cases:
            agent_result = {
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
                "execution_time_seconds": exec_time
            }
            
            result = calculator.calculate_profit_score(
                agent_config=agent_config,
                agent_result=agent_result,
                task_revenue=500
            )
            
            assert result["e2b_cost"] == expected_cost, \
                f"Expected {expected_cost} cents for {exec_time}s, got {result['e2b_cost']}"
    
    # =============================================================================
    # EDGE CASES
    # =============================================================================
    
    def test_zero_execution_time(self):
        """Test profit calculation with zero execution time."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o-mini"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(
            name="TestAgent",
            llm_service=mock_llm
        )
        
        agent_result = {
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            "execution_time_seconds": 0
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=500
        )
        
        assert result["e2b_cost"] == 0
    
    def test_zero_task_revenue(self):
        """Test profit calculation with zero task revenue."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "llama3.2"
        mock_llm.is_local.return_value = True
        
        agent_config = AgentConfig(
            name="TestAgent",
            llm_service=mock_llm
        )
        
        agent_result = {
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            "execution_time_seconds": 30
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=0
        )
        
        assert result["revenue"] == 0
        assert result["profit"] == -2.5  # -E2B cost (2.5 cents for 30s)
        assert result["is_profitable"] is False
    
    def test_empty_usage(self):
        """Test profit calculation with empty usage data."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(
            name="TestAgent",
            llm_service=mock_llm
        )
        
        # Empty usage
        agent_result = {
            "usage": {},
            "execution_time_seconds": 60
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=500
        )
        
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0
        assert result["total_tokens"] == 0
        assert result["llm_cost"] == 0  # Zero tokens = zero cost
    
    def test_nested_usage_data(self):
        """Test profit calculation with nested usage in steps."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(
            name="TestAgent",
            llm_service=mock_llm
        )
        
        # Usage in nested steps
        agent_result = {
            "steps": {
                "context_extraction": {
                    "usage": {"prompt_tokens": 500, "completion_tokens": 200}
                },
                "plan_generation": {
                    "usage": {"prompt_tokens": 800, "completion_tokens": 300}
                },
                "plan_execution": {
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 400}
                }
            },
            "execution_time_seconds": 120
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=500
        )
        
        # Total: 500+800+1000 input = 2300, 200+300+400 output = 900
        assert result["input_tokens"] == 2300
        assert result["output_tokens"] == 900
    
    # =============================================================================
    # PARAMETRIZED TESTS
    # =============================================================================
    
    @pytest.mark.parametrize("model,is_local,expected_cost_type", [
        ("gpt-4o", False, "gpt4o"),
        ("gpt-4o-mini", False, "gpt4o_mini"),
        ("llama3.2", True, "local"),
        ("mistral", True, "local"),
        ("claude-3", False, "gpt4o_mini"),  # Falls back to mini pricing
    ])
    def test_model_cost_types(self, model, is_local, expected_cost_type):
        """Test that different model types get correct cost calculations."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = model
        mock_llm.is_local.return_value = is_local
        
        agent_config = AgentConfig(
            name="TestAgent",
            llm_service=mock_llm
        )
        
        agent_result = {
            "usage": {"prompt_tokens": 1000000, "completion_tokens": 1000000},
            "execution_time_seconds": 60
        }
        
        result = calculator.calculate_profit_score(
            agent_config=agent_config,
            agent_result=agent_result,
            task_revenue=10000  # $100 to ensure profit
        )
        
        if expected_cost_type == "local":
            assert result["llm_cost"] == 0
        elif expected_cost_type == "gpt4o":
            assert result["llm_cost"] == 1250
        elif expected_cost_type == "gpt4o_mini":
            assert result["llm_cost"] == 75


class TestCostConfig:
    """Test CostConfig class."""
    
    def test_default_cost_config_values(self):
        """Test default cost config values."""
        config = CostConfig()
        
        # Verify default values exist and are correct
        assert config.CLOUD_GPT4O_INPUT_COST == 250
        assert config.CLOUD_GPT4O_OUTPUT_COST == 1000
        assert config.CLOUD_GPT4O_MINI_INPUT_COST == 15
        assert config.CLOUD_GPT4O_MINI_OUTPUT_COST == 60
        assert config.LOCAL_COST == 0
        assert config.E2B_COST_PER_MINUTE == 5
        assert config.DEFAULT_TASK_REVENUE == 500
    
    def test_e2b_cost_per_minute(self):
        """Test E2B cost is per minute."""
        config = CostConfig()
        
        # 1 minute = 5 cents
        assert config.E2B_COST_PER_MINUTE == 5
        
        # Verify the calculation in profit calculator
        calculator = ProfitCalculator(config)
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "test"
        mock_llm.is_local.return_value = True
        
        agent_config = AgentConfig(name="test", llm_service=mock_llm)
        
        for minutes in [1, 2, 5, 10]:
            result = calculator.calculate_profit_score(
                agent_config,
                {"execution_time_seconds": minutes * 60},
                10000
            )
            assert result["e2b_cost"] == minutes * 5


class TestProfitBreakdown:
    """Test profit breakdown structure."""
    
    def test_profit_breakdown_keys(self):
        """Test all expected keys are in profit breakdown."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o-mini"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(name="test", llm_service=mock_llm)
        
        result = calculator.calculate_profit_score(
            agent_config,
            {"usage": {}, "execution_time_seconds": 60},
            500
        )
        
        required_keys = [
            "profit", "revenue", "llm_cost", "input_cost", "output_cost",
            "e2b_cost", "total_cost", "input_tokens", "output_tokens",
            "total_tokens", "execution_time_seconds", "is_profitable"
        ]
        
        for key in required_keys:
            assert key in result, f"Missing key: {key}"
    
    def test_profit_equals_revenue_minus_total_cost(self):
        """Test profit = revenue - total_cost."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(name="test", llm_service=mock_llm)
        
        result = calculator.calculate_profit_score(
            agent_config,
            {
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
                "execution_time_seconds": 60
            },
            task_revenue=500
        )
        
        expected_profit = result["revenue"] - result["total_cost"]
        assert result["profit"] == expected_profit
    
    def test_total_cost_equals_llm_plus_e2b(self):
        """Test total_cost = llm_cost + e2b_cost."""
        calculator = ProfitCalculator()
        
        mock_llm = Mock()
        mock_llm.get_model.return_value = "gpt-4o"
        mock_llm.is_local.return_value = False
        
        agent_config = AgentConfig(name="test", llm_service=mock_llm)
        
        result = calculator.calculate_profit_score(
            agent_config,
            {
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
                "execution_time_seconds": 60
            },
            task_revenue=500
        )
        
        expected_total = result["llm_cost"] + result["e2b_cost"]
        assert result["total_cost"] == expected_total
