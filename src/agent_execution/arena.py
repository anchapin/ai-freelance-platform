"""
Agent Arena Module

This module implements the Agent Arena competition system where two agent variants
compete on the same task. The winner is determined by:
1. Artifact quality (passed PlanReviewer)
2. Profit score (Task Revenue - LLM Cost - E2B Compute Cost)

The learning loop:
- Winner → ExperienceVectorDB + DistillationDataCollector (positive examples)
- Loser → DPO Dataset (Direct Preference Optimization - negative examples)

This creates an automated benchmark system where local models (P40) compete against
cloud models (GPT-4o) and learn from their successes/failures.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

# Import logging module
from src.utils.logger import get_logger

from src.llm_service import LLMService
from src.agent_execution.planning import (
    ResearchAndPlanOrchestrator,
    ContextExtractor,
    WorkPlanGenerator,
    PlanExecutor,
    PlanReviewer
)

# Import Traceloop decorators for OpenTelemetry observability
from traceloop.sdk.decorators import workflow, task


# =============================================================================
# COST CONFIGURATION
# =============================================================================

class CostConfig:
    """Cost configuration for profit calculations."""
    
    # LLM Costs (per 1M tokens, in cents)
    # GPT-4o Input: $2.50/1M, Output: $10.00/1M
    CLOUD_GPT4O_INPUT_COST = 250    # $2.50/1M input tokens
    CLOUD_GPT4O_OUTPUT_COST = 1000  # $10.00/1M output tokens
    
    # GPT-4o-mini Input: $0.15/1M, Output: $0.60/1M
    CLOUD_GPT4O_MINI_INPUT_COST = 15   # $0.15/1M input tokens
    CLOUD_GPT4O_MINI_OUTPUT_COST = 60  # $0.60/1M output tokens
    
    LOCAL_COST = 0                # Local P40 has no API cost
    
    # E2B Compute Costs (per minute, in cents)
    E2B_COST_PER_MINUTE = 5      # $0.05/min sandbox
    
    # Default task revenue (if not provided)
    DEFAULT_TASK_REVENUE = 500   # $5.00 default task value


# =============================================================================
# COMPETITION TYPES
# =============================================================================

class CompetitionType(Enum):
    """Types of A/B competitions."""
    MODEL = "model"           # Local vs Cloud model
    PROMPT = "prompt"         # Cautious vs Fast prompt
    TOOLING = "tooling"       # Different retry/planning configs


class AgentConfig:
    """Configuration for an arena agent."""
    
    def __init__(
        self,
        name: str,
        llm_service: LLMService,
        system_prompt_style: str = "standard",
        max_retries: int = 2,
        planning_time_multiplier: float = 1.0
    ):
        self.name = name
        self.llm_service = llm_service
        self.system_prompt_style = system_prompt_style
        self.max_retries = max_retries
        self.planning_time_multiplier = planning_time_multiplier
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.llm_service.get_model(),
            "is_local": self.llm_service.is_local(),
            "system_prompt_style": self.system_prompt_style,
            "max_retries": self.max_retries,
            "planning_time_multiplier": self.planning_time_multiplier
        }


# =============================================================================
# PROFIT CALCULATOR
# =============================================================================

class ProfitCalculator:
    """Calculates profit score for arena agents."""
    
    def __init__(self, cost_config: CostConfig = None):
        self.cost_config = cost_config or CostConfig()
    
    def calculate_profit_score(
        self,
        agent_config: AgentConfig,
        agent_result: Dict[str, Any],
        task_revenue: int
    ) -> Dict[str, Any]:
        """
        Calculate profit score for an agent.
        
        Profit = Task Revenue - (LLM Cost + E2B Compute Cost)
        
        Args:
            agent_config: The agent configuration
            agent_result: The result from executing the task
            task_revenue: The revenue from the task (in cents)
            
        Returns:
            Dictionary with profit breakdown
        """
        # Calculate LLM cost based on model type
        is_local = agent_config.llm_service.is_local()
        
        # Aggregate token usage from all LLM calls in the execution
        total_input_tokens = 0
        total_output_tokens = 0
        
        # Extract usage from result (could be nested)
        if "usage" in agent_result:
            usage = agent_result.get("usage", {})
            total_input_tokens = usage.get("prompt_tokens", 0)
            total_output_tokens = usage.get("completion_tokens", 0)
        
        # Check for nested usage in steps
        steps = agent_result.get("steps", {})
        for step_name, step_result in steps.items():
            if isinstance(step_result, dict) and "usage" in step_result:
                usage = step_result.get("usage", {})
                total_input_tokens += usage.get("prompt_tokens", 0)
                total_output_tokens += usage.get("completion_tokens", 0)
        
        total_tokens = total_input_tokens + total_output_tokens
        
        # Calculate LLM cost (separately for input and output tokens)
        if is_local:
            llm_cost = 0  # Local models cost nothing in API fees
            input_cost = 0
            output_cost = 0
        else:
            model = agent_config.llm_service.get_model()
            if "gpt-4o" in model.lower() and "mini" not in model.lower():
                # GPT-4o: separate input and output rates
                input_cost = (total_input_tokens / 1_000_000) * self.cost_config.CLOUD_GPT4O_INPUT_COST
                output_cost = (total_output_tokens / 1_000_000) * self.cost_config.CLOUD_GPT4O_OUTPUT_COST
            else:
                # GPT-4o-mini: separate input and output rates
                input_cost = (total_input_tokens / 1_000_000) * self.cost_config.CLOUD_GPT4O_MINI_INPUT_COST
                output_cost = (total_output_tokens / 1_000_000) * self.cost_config.CLOUD_GPT4O_MINI_OUTPUT_COST
            llm_cost = input_cost + output_cost
        
        # Calculate E2B compute time cost
        execution_time = agent_result.get("execution_time_seconds", 0)
        e2b_cost = (execution_time / 60) * self.cost_config.E2B_COST_PER_MINUTE
        
        # Calculate total cost and profit
        total_cost = llm_cost + e2b_cost
        profit = task_revenue - total_cost
        
        return {
            "profit": profit,
            "revenue": task_revenue,
            "llm_cost": llm_cost,
            "input_cost": input_cost,
            "output_cost": output_cost,
            "e2b_cost": e2b_cost,
            "total_cost": total_cost,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
            "execution_time_seconds": execution_time,
            "is_profitable": profit > 0
        }


# =============================================================================
# ARENA AGENT (Single Competitor)
# =============================================================================

class ArenaAgent:
    """A single agent competitor in the arena."""
    
    def __init__(
        self,
        config: AgentConfig,
        domain: str,
        max_retries: int = 2
    ):
        self.config = config
        self.domain = domain
        self.max_retries = max_retries
        
        # Create the orchestrator with this agent's LLM
        self.orchestrator = ResearchAndPlanOrchestrator(
            llm_service=config.llm_service,
            domain=domain
        )
        
        self.result: Optional[Dict[str, Any]] = None
        self.execution_time: float = 0
    
    async def execute(
        self,
        user_request: str,
        csv_data: Optional[str] = None,
        file_content: Optional[str] = None,
        filename: Optional[str] = None,
        file_type: Optional[str] = None,
        api_key: Optional[str] = None,
        task_type: Optional[str] = None,
        output_format: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute the task as this agent.
        
        Returns:
            Dictionary with execution results including timing and usage
        """
        start_time = time.time()
        
        try:
            # Run the workflow (synchronous, we'll wrap in asyncio)
            result = self.orchestrator.execute_workflow(
                user_request=user_request,
                domain=self.domain,
                csv_data=csv_data,
                file_content=file_content,
                filename=filename,
                file_type=file_type,
                api_key=api_key,
                task_type=task_type,
                output_format=output_format,
                max_review_attempts=self.max_retries + 1  # retries + initial
            )
            
            self.execution_time = time.time() - start_time
            self.result = result
            
            return {
                "success": result.get("success", False),
                "approved": result.get("steps", {}).get("artifact_review", {}).get("approved", False),
                "feedback": result.get("steps", {}).get("artifact_review", {}).get("feedback", ""),
                "artifact_url": result.get("artifact_url"),
                "execution_time_seconds": self.execution_time,
                "steps": result.get("steps", {}),
                "error": result.get("error"),
                "failed_at": result.get("failed_at"),
                "full_result": result
            }
            
        except Exception as e:
            self.execution_time = time.time() - start_time
            self.result = {"error": str(e)}
            
            return {
                "success": False,
                "approved": False,
                "error": str(e),
                "execution_time_seconds": self.execution_time,
                "full_result": {"error": str(e)}
            }


# =============================================================================
# ARENA ROUTER (Main Competition Orchestrator)
# =============================================================================

class ArenaRouter:
    """
    Main orchestrator for Agent Arena competitions.
    
    Runs two agent variants in parallel and determines the winner
    based on quality + profit score.
    """
    
    def __init__(
        self,
        competition_type: CompetitionType = CompetitionType.MODEL,
        cost_config: CostConfig = None
    ):
        self.competition_type = competition_type
        self.cost_config = cost_config or CostConfig()
        self.profit_calculator = ProfitCalculator(self.cost_config)
        
        # Setup the two competing agents
        self.agent_a = self._create_agent_a()
        self.agent_b = self._create_agent_b()
    
    def _create_agent_a(self) -> AgentConfig:
        """Create Agent A - Local model (Llama-3.2 P40)."""
        if self.competition_type == CompetitionType.MODEL:
            # Agent A: Local model - high profit margin
            return AgentConfig(
                name="Agent_A_Local",
                llm_service=LLMService.with_local(model="llama3.2"),
                system_prompt_style="standard",
                max_retries=0,
                planning_time_multiplier=2.0  # More planning time
            )
        elif self.competition_type == CompetitionType.PROMPT:
            # Agent A: Cautious & Detailed prompt
            return AgentConfig(
                name="Agent_A_Cautious",
                llm_service=LLMService.with_cloud(model="gpt-4o-mini"),
                system_prompt_style="cautious_detailed",
                max_retries=3
            )
        else:  # TOOLING
            # Agent A: 3 retries allowed
            return AgentConfig(
                name="Agent_A_Retries",
                llm_service=LLMService.with_cloud(model="gpt-4o-mini"),
                system_prompt_style="standard",
                max_retries=3
            )
    
    def _create_agent_b(self) -> AgentConfig:
        """Create Agent B - Cloud model (GPT-4o-mini)."""
        if self.competition_type == CompetitionType.MODEL:
            # Agent B: Cloud model - higher accuracy
            return AgentConfig(
                name="Agent_B_Cloud",
                llm_service=LLMService.with_cloud(model="gpt-4o-mini"),
                system_prompt_style="standard",
                max_retries=2
            )
        elif self.competition_type == CompetitionType.PROMPT:
            # Agent B: Fast & Minimalist prompt
            return AgentConfig(
                name="Agent_B_Fast",
                llm_service=LLMService.with_cloud(model="gpt-4o-mini"),
                system_prompt_style="fast_minimalist",
                max_retries=1
            )
        else:  # TOOLING
            # Agent B: 0 retries but longer planning
            return AgentConfig(
                name="Agent_B_NoRetries",
                llm_service=LLMService.with_cloud(model="gpt-4o-mini"),
                system_prompt_style="standard",
                max_retries=0,
                planning_time_multiplier=2.0
            )
    
    @task(name="arena_competition")
    async def run_arena(
        self,
        user_request: str,
        domain: str,
        csv_data: Optional[str] = None,
        file_content: Optional[str] = None,
        filename: Optional[str] = None,
        file_type: Optional[str] = None,
        api_key: Optional[str] = None,
        task_type: Optional[str] = None,
        output_format: Optional[str] = None,
        task_revenue: int = None
    ) -> Dict[str, Any]:
        """
        Run the arena competition.
        
        Args:
            user_request: The user's task request
            domain: The task domain (legal, accounting, data_analysis)
            csv_data: Optional CSV data
            file_content: Optional file content
            filename: Optional filename
            file_type: Optional file type
            api_key: E2B API key
            task_type: Optional task type
            output_format: Optional output format
            task_revenue: Task revenue in cents (optional)
            
        Returns:
            Arena result with winner and detailed metrics
        """
        # Get logger for this class
        logger = get_logger(__name__)
        
        task_revenue = task_revenue or self.cost_config.DEFAULT_TASK_REVENUE
        
        # Create arena agents
        arena_agent_a = ArenaAgent(
            config=self.agent_a,
            domain=domain,
            max_retries=self.agent_a.max_retries
        )
        
        arena_agent_b = ArenaAgent(
            config=self.agent_b,
            domain=domain,
            max_retries=self.agent_b.max_retries
        )
        
        # Run both agents in parallel
        logger.info(f"Starting Arena Competition: {self.competition_type.value}")
        logger.info(f"Agent A: {self.agent_a.name} ({self.agent_a.llm_service.get_model()})")
        logger.info(f"Agent B: {self.agent_b.name} ({self.agent_b.llm_service.get_model()})")
        
        # Execute both agents concurrently
        task_a = arena_agent_a.execute(
            user_request=user_request,
            csv_data=csv_data,
            file_content=file_content,
            filename=filename,
            file_type=file_type,
            api_key=api_key,
            task_type=task_type,
            output_format=output_format
        )
        
        task_b = arena_agent_b.execute(
            user_request=user_request,
            csv_data=csv_data,
            file_content=file_content,
            filename=filename,
            file_type=file_type,
            api_key=api_key,
            task_type=task_type,
            output_format=output_format
        )
        
        result_a, result_b = await asyncio.gather(task_a, task_b)
        
        logger.info(f"Agent A completed in {result_a.get('execution_time_seconds', 0):.1f}s")
        logger.info(f"Agent B completed in {result_b.get('execution_time_seconds', 0):.1f}s")
        
        # Calculate profit scores
        profit_a = self.profit_calculator.calculate_profit_score(
            agent_config=self.agent_a,
            agent_result=result_a,
            task_revenue=task_revenue
        )
        
        profit_b = self.profit_calculator.calculate_profit_score(
            agent_config=self.agent_b,
            agent_result=result_b,
            task_revenue=task_revenue
        )
        
        # Determine winner
        winner, win_reason = self._determine_winner(result_a, result_b, profit_a, profit_b)
        
        # Prepare final result
        arena_result = {
            "competition_type": self.competition_type.value,
            "task_revenue": task_revenue,
            "agent_a": {
                "config": self.agent_a.to_dict(),
                "result": result_a,
                "profit": profit_a
            },
            "agent_b": {
                "config": self.agent_b.to_dict(),
                "result": result_b,
                "profit": profit_b
            },
            "winner": winner,
            "win_reason": win_reason,
            "winning_artifact_url": result_a.get("artifact_url") if winner == "agent_a" else result_b.get("artifact_url"),
            "completed_at": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Winner: {winner} | Reason: {win_reason}")
        
        return arena_result
    
    def _determine_winner(
        self,
        result_a: Dict[str, Any],
        result_b: Dict[str, Any],
        profit_a: Dict[str, Any],
        profit_b: Dict[str, Any]
    ) -> tuple:
        """
        Determine the winner based on quality + profit.
        
        Rules:
        - If one passes and other fails: passer wins
        - If both pass: higher profit wins
        - If both fail: lower loss wins
        """
        approved_a = result_a.get("approved", False)
        approved_b = result_b.get("approved", False)
        
        # Case 1: One passes, one fails
        if approved_a and not approved_b:
            return "agent_a", "Passed review, Agent B failed"
        if approved_b and not approved_a:
            return "agent_b", "Passed review, Agent A failed"
        
        # Case 2: Both pass - check profit
        if approved_a and approved_b:
            if profit_a["profit"] > profit_b["profit"]:
                return "agent_a", f"Higher profit: ${profit_a['profit']/100:.2f} vs ${profit_b['profit']/100:.2f}"
            else:
                return "agent_b", f"Higher profit: ${profit_b['profit']/100:.2f} vs ${profit_a['profit']/100:.2f}"
        
        # Case 3: Both fail - lower loss wins
        if not approved_a and not approved_b:
            if profit_a["profit"] > profit_b["profit"]:
                return "agent_a", "Both failed, but lower loss"
            else:
                return "agent_b", "Both failed, but lower loss"
        
        # Case 4: Edge case (shouldn't reach here)
        return "agent_a", "Default to Agent A"


# =============================================================================
# ARENA INTEGRATION WITH LEARNING
# =============================================================================

class ArenaLearningLogger:
    """
    Logs arena results for learning.
    
    - Winner → ExperienceVectorDB + DistillationDataCollector
    - Loser → DPO Dataset
    """
    
    def __init__(self):
        self.dpo_dataset_path = "data/dpo_dataset.jsonl"
        self.logger = get_logger(__name__)
    
    def log_winner(
        self,
        arena_result: Dict[str, Any],
        task_data: Dict[str, Any]
    ):
        """
        Log winning example to ExperienceVectorDB and DistillationDataCollector.
        """
        winner_key = arena_result["winner"]
        winner_data = arena_result[winner_key]
        
        # Get the successful code/artifacts from winner
        winner_result = winner_data.get("result", {})
        
        try:
            # Store in ExperienceVectorDB (for RAG)
            from src.experience_vector_db import store_successful_task
            store_successful_task(
                task_request=task_data.get("description", ""),
                task_domain=task_data.get("domain", ""),
                successful_output=json.dumps(winner_result),
                task_id=task_data.get("id")
            )
            self.logger.info(f"Logged winner to ExperienceVectorDB")
        except Exception as e:
            self.logger.warning(f"Failed to log to ExperienceVectorDB: {e}")
        
        try:
            # Store for distillation training
            from src.distillation.data_collector import DistillationDataCollector
            collector = DistillationDataCollector()
            collector.collect_success(
                task_request=task_data.get("description", ""),
                domain=task_data.get("domain", ""),
                llm_output=json.dumps(winner_result),
                model_used=winner_data["config"]["model"]
            )
            self.logger.info(f"Logged winner to DistillationDataCollector")
        except Exception as e:
            self.logger.warning(f"Failed to log to DistillationDataCollector: {e}")
    
    def log_loser(
        self,
        arena_result: Dict[str, Any],
        task_data: Dict[str, Any]
    ):
        """
        Log losing example to DPO dataset for preference optimization.
        """
        winner_key = arena_result["winner"]
        loser_key = "agent_b" if winner_key == "agent_a" else "agent_a"
        
        winner_data = arena_result[winner_key]
        loser_data = arena_result[loser_key]
        
        winner_result = winner_data.get("result", {})
        loser_result = loser_data.get("result", {})
        
        dpo_example = {
            "task_id": task_data.get("id"),
            "domain": task_data.get("domain"),
            "user_request": task_data.get("description"),
            "task_revenue": arena_result.get("task_revenue"),
            
            # Chosen (winner) - what to do
            "chosen": {
                "model": winner_data["config"]["model"],
                "system_prompt_style": winner_data["config"]["system_prompt_style"],
                "max_retries": winner_data["config"]["max_retries"],
                "generated_code": self._extract_code(winner_result),
                "success": winner_result.get("success", False)
            },
            
            # Rejected (loser) - what NOT to do
            "rejected": {
                "model": loser_data["config"]["model"],
                "system_prompt_style": loser_data["config"]["system_prompt_style"],
                "max_retries": loser_data["config"]["max_retries"],
                "generated_code": self._extract_code(loser_result),
                "failure_reason": loser_result.get("error") or loser_result.get("feedback", ""),
                "success": loser_result.get("success", False)
            },
            
            # Metadata
            "profit_diff": winner_data["profit"]["profit"] - loser_data["profit"]["profit"],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Append to DPO dataset
        try:
            import os
            os.makedirs(os.path.dirname(self.dpo_dataset_path), exist_ok=True)
            with open(self.dpo_dataset_path, "a") as f:
                f.write(json.dumps(dpo_example) + "\n")
            self.logger.info(f"Logged loser to DPO dataset")
        except Exception as e:
            self.logger.warning(f"Failed to log to DPO dataset: {e}")
    
    def _extract_code(self, result: Dict[str, Any]) -> str:
        """Extract generated code from agent result."""
        # Try various paths where code might be stored
        steps = result.get("steps", {})
        
        # From plan execution
        if "plan_execution" in steps:
            exec_result = steps["plan_execution"].get("result", {})
            if "code" in exec_result:
                return exec_result["code"]
        
        # From visualization
        if "artifact_review" in steps:
            # Code might be in execution log
            pass
        
        return ""


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

@workflow(name="agent_arena_workflow")
async def run_agent_arena(
    user_request: str,
    domain: str,
    csv_data: Optional[str] = None,
    file_content: Optional[str] = None,
    filename: Optional[str] = None,
    file_type: Optional[str] = None,
    api_key: Optional[str] = None,
    competition_type: CompetitionType = CompetitionType.MODEL,
    task_revenue: int = None,
    enable_learning: bool = True,
    task_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Convenience function to run an arena competition.
    
    Args:
        user_request: User's task request
        domain: Task domain
        csv_data: Optional CSV data
        file_content: Optional file content
        filename: Optional filename
        file_type: Optional file type
        api_key: E2B API key
        competition_type: Type of competition
        task_revenue: Task revenue in cents
        enable_learning: Whether to log to learning systems
        task_data: Task metadata for logging
        
    Returns:
        Arena result with winner
    """
    # Create and run arena
    arena = ArenaRouter(competition_type=competition_type)
    
    result = await arena.run_arena(
        user_request=user_request,
        domain=domain,
        csv_data=csv_data,
        file_content=file_content,
        filename=filename,
        file_type=file_type,
        api_key=api_key,
        task_revenue=task_revenue
    )
    
    # Log learning data if enabled
    if enable_learning and task_data:
        logger = ArenaLearningLogger()
        logger.log_winner(result, task_data)
        logger.log_loser(result, task_data)
    
    return result


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Get logger for example code
    logger = get_logger("arena_example")
    
    async def example():
        # Run a model competition
        result = await run_agent_arena(
            user_request="Create a bar chart showing monthly sales data",
            domain="data_analysis",
            csv_data="month,sales\nJan,100\nFeb,150\nMar,200",
            competition_type=CompetitionType.MODEL,
            task_revenue=500  # $5.00
        )
        
        logger.info(f"Arena Result - Winner: {result['winner']}, Reason: {result['win_reason']}")
        
        # Profit breakdown
        winner_key = result["winner"]
        profit = result[winner_key]["profit"]
        logger.info(f"Profit Breakdown - Revenue: ${profit['revenue']/100:.2f}, "
                   f"LLM Cost: ${profit['llm_cost']/100:.2f}, "
                   f"E2B Cost: ${profit['e2b_cost']/100:.2f}, "
                   f"Total Cost: ${profit['total_cost']/100:.2f}, "
                   f"Profit: ${profit['profit']/100:.2f}")
    
    # Run example
    asyncio.run(example())
