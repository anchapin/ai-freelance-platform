"""
Unit tests for calculate_task_price function.

This module tests the Task Price Formula:
Price = Base Rate × Complexity × Urgency

Critical: Errors in this formula directly impact revenue.
"""

import pytest
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from src.api.main import calculate_task_price, DOMAIN_BASE_RATES, COMPLEXITY_MULTIPLIERS, URGENCY_MULTIPLIERS


class TestCalculateTaskPrice:
    """Test suite for calculate_task_price function."""
    
    # =============================================================================
    # BASIC DOMAIN TESTS
    # =============================================================================
    
    def test_accounting_domain_base_price(self):
        """Test accounting domain returns correct base price."""
        price = calculate_task_price("accounting", "simple", "standard")
        assert price == 100  # $100 * 1.0 * 1.0
    
    def test_legal_domain_base_price(self):
        """Test legal domain returns correct base price."""
        price = calculate_task_price("legal", "simple", "standard")
        assert price == 175  # $175 * 1.0 * 1.0
    
    def test_data_analysis_domain_base_price(self):
        """Test data_analysis domain returns correct base price."""
        price = calculate_task_price("data_analysis", "simple", "standard")
        assert price == 150  # $150 * 1.0 * 1.0
    
    # =============================================================================
    # COMPLEXITY MULTIPLIER TESTS
    # =============================================================================
    
    def test_simple_complexity(self):
        """Test simple complexity returns 1.0 multiplier."""
        price = calculate_task_price("accounting", "simple", "standard")
        assert price == 100
    
    def test_medium_complexity(self):
        """Test medium complexity returns 1.5 multiplier."""
        price = calculate_task_price("accounting", "medium", "standard")
        assert price == 150  # $100 * 1.5
    
    def test_complex_complexity(self):
        """Test complex complexity returns 2.0 multiplier."""
        price = calculate_task_price("accounting", "complex", "standard")
        assert price == 200  # $100 * 2.0
    
    # =============================================================================
    # URGENCY MULTIPLIER TESTS
    # =============================================================================
    
    def test_standard_urgency(self):
        """Test standard urgency returns 1.0 multiplier."""
        price = calculate_task_price("accounting", "simple", "standard")
        assert price == 100
    
    def test_rush_urgency(self):
        """Test rush urgency returns 1.25 multiplier."""
        price = calculate_task_price("accounting", "simple", "rush")
        assert price == 125  # $100 * 1.25
    
    def test_urgent_urgency(self):
        """Test urgent urgency returns 1.5 multiplier."""
        price = calculate_task_price("accounting", "simple", "urgent")
        assert price == 150  # $100 * 1.5
    
    # =============================================================================
    # COMBINED MULTIPLIER TESTS
    # =============================================================================
    
    def test_medium_complexity_rush_urgency(self):
        """Test medium complexity with rush urgency."""
        price = calculate_task_price("accounting", "medium", "rush")
        assert price == 188  # $100 * 1.5 * 1.25 = 187.5 → 188
    
    def test_complex_complexity_urgent_urgency(self):
        """Test complex complexity with urgent urgency (highest multiplier)."""
        price = calculate_task_price("accounting", "complex", "urgent")
        assert price == 300  # $100 * 2.0 * 1.5
    
    def test_legal_complex_rush(self):
        """Test legal domain with complex and rush."""
        price = calculate_task_price("legal", "complex", "rush")
        # $175 * 2.0 * 1.25 = 437.5 → 438
        assert price == 438
    
    def test_data_analysis_medium_standard(self):
        """Test data_analysis with medium complexity, standard urgency."""
        price = calculate_task_price("data_analysis", "medium", "standard")
        assert price == 225  # $150 * 1.5 * 1.0
    
    # =============================================================================
    # EDGE CASES
    # =============================================================================
    
    def test_lowest_price(self):
        """Test the lowest possible price (simple + standard)."""
        price = calculate_task_price("accounting", "simple", "standard")
        assert price == 100
    
    def test_highest_price(self):
        """Test the highest possible price (complex + urgent)."""
        price = calculate_task_price("legal", "complex", "urgent")
        # $175 * 2.0 * 1.5 = 525
        assert price == 525
    
    def test_default_parameters(self):
        """Test default parameters (medium complexity, standard urgency)."""
        price = calculate_task_price("accounting")
        assert price == 150  # Default: medium, standard
    
    # =============================================================================
    # ERROR HANDLING TESTS
    # =============================================================================
    
    def test_invalid_domain_raises_error(self):
        """Test invalid domain raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            calculate_task_price("invalid_domain", "simple", "standard")
        
        assert "Invalid domain" in str(exc_info.value)
        assert "accounting, legal, data_analysis" in str(exc_info.value)
    
    def test_invalid_complexity_raises_error(self):
        """Test invalid complexity raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            calculate_task_price("accounting", "invalid", "standard")
        
        assert "Invalid complexity" in str(exc_info.value)
    
    def test_invalid_urgency_raises_error(self):
        """Test invalid urgency raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            calculate_task_price("accounting", "simple", "invalid")
        
        assert "Invalid urgency" in str(exc_info.value)
    
    def test_empty_domain_raises_error(self):
        """Test empty domain raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            calculate_task_price("", "simple", "standard")
        
        assert "Invalid domain" in str(exc_info.value)
    
    # =============================================================================
    # TEST DATA DRIVEN APPROACH
    # =============================================================================
    
    @pytest.mark.parametrize("domain,complexity,urgency,expected", [
        # Accounting tests
        ("accounting", "simple", "standard", 100),
        ("accounting", "medium", "standard", 150),
        ("accounting", "complex", "standard", 200),
        ("accounting", "simple", "rush", 125),
        ("accounting", "simple", "urgent", 150),
        ("accounting", "medium", "rush", 188),
        ("accounting", "medium", "urgent", 225),
        ("accounting", "complex", "rush", 250),
        ("accounting", "complex", "urgent", 300),
        # Legal tests
        ("legal", "simple", "standard", 175),
        ("legal", "medium", "standard", 262),
        ("legal", "complex", "standard", 350),
        ("legal", "simple", "rush", 219),
        ("legal", "simple", "urgent", 262),
        ("legal", "medium", "rush", 328),
        ("legal", "medium", "urgent", 394),
        ("legal", "complex", "rush", 438),
        ("legal", "complex", "urgent", 525),
        # Data Analysis tests
        ("data_analysis", "simple", "standard", 150),
        ("data_analysis", "medium", "standard", 225),
        ("data_analysis", "complex", "standard", 300),
        ("data_analysis", "simple", "rush", 188),
        ("data_analysis", "simple", "urgent", 225),
        ("data_analysis", "medium", "rush", 281),
        ("data_analysis", "medium", "urgent", 338),
        ("data_analysis", "complex", "rush", 375),
        ("data_analysis", "complex", "urgent", 450),
    ])
    def test_price_calculation_parametrized(self, domain, complexity, urgency, expected):
        """Test price calculation with various combinations."""
        price = calculate_task_price(domain, complexity, urgency)
        assert price == expected


class TestPricingConstants:
    """Test pricing constants are correctly defined."""
    
    def test_domain_base_rates(self):
        """Test domain base rates are correctly set."""
        assert DOMAIN_BASE_RATES["accounting"] == 100
        assert DOMAIN_BASE_RATES["legal"] == 175
        assert DOMAIN_BASE_RATES["data_analysis"] == 150
    
    def test_complexity_multipliers(self):
        """Test complexity multipliers are correctly set."""
        assert COMPLEXITY_MULTIPLIERS["simple"] == 1.0
        assert COMPLEXITY_MULTIPLIERS["medium"] == 1.5
        assert COMPLEXITY_MULTIPLIERS["complex"] == 2.0
    
    def test_urgency_multipliers(self):
        """Test urgency multipliers are correctly set."""
        assert URGENCY_MULTIPLIERS["standard"] == 1.0
        assert URGENCY_MULTIPLIERS["rush"] == 1.25
        assert URGENCY_MULTIPLIERS["urgent"] == 1.5
    
    def test_all_domains_have_base_rates(self):
        """Test all domains have base rates defined."""
        for domain in ["accounting", "legal", "data_analysis"]:
            assert domain in DOMAIN_BASE_RATES
            assert DOMAIN_BASE_RATES[domain] > 0
    
    def test_all_complexities_have_multipliers(self):
        """Test all complexity levels have multipliers defined."""
        for complexity in ["simple", "medium", "complex"]:
            assert complexity in COMPLEXITY_MULTIPLIERS
            assert COMPLEXITY_MULTIPLIERS[complexity] > 0
    
    def test_all_urgencies_have_multipliers(self):
        """Test all urgency levels have multipliers defined."""
        for urgency in ["standard", "rush", "urgent"]:
            assert urgency in URGENCY_MULTIPLIERS
            assert URGENCY_MULTIPLIERS[urgency] > 0


class TestPricingFormula:
    """Test the pricing formula logic."""
    
    def test_formula_uses_correct_defaults(self):
        """Test formula uses correct defaults."""
        # These are different parameter orders, not different multipliers
        # The function uses complexity and urgency as PARAMETER names
        price = calculate_task_price("accounting", "medium", "standard")
        assert price == 150
    
    def test_multipliers_are_greater_than_zero(self):
        """Test all multipliers are positive."""
        for mult in COMPLEXITY_MULTIPLIERS.values():
            assert mult > 0
        for mult in URGENCY_MULTIPLIERS.values():
            assert mult > 0
    
    def test_base_rates_are_greater_than_zero(self):
        """Test all base rates are positive."""
        for rate in DOMAIN_BASE_RATES.values():
            assert rate > 0
    
    def test_price_always_at_least_base_rate(self):
        """Test price is always at least the base rate."""
        for domain in DOMAIN_BASE_RATES:
            for complexity in COMPLEXITY_MULTIPLIERS:
                for urgency in URGENCY_MULTIPLIERS:
                    price = calculate_task_price(domain, complexity, urgency)
                    assert price >= DOMAIN_BASE_RATES[domain]
    
    def test_price_increases_with_complexity(self):
        """Test price increases with complexity level."""
        simple = calculate_task_price("accounting", "simple", "standard")
        medium = calculate_task_price("accounting", "medium", "standard")
        complex = calculate_task_price("accounting", "complex", "standard")
        
        assert simple < medium < complex
    
    def test_price_increases_with_urgency(self):
        """Test price increases with urgency level."""
        standard = calculate_task_price("accounting", "simple", "standard")
        rush = calculate_task_price("accounting", "simple", "rush")
        urgent = calculate_task_price("accounting", "simple", "urgent")
        
        assert standard < rush < urgent
