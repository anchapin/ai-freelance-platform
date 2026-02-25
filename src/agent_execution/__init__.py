"""
Agent Execution Module

This module provides functionality for executing code in secure sandboxes
using the E2B Code Interpreter SDK.

Features:
- TaskRouter: Routes tasks to appropriate handlers based on domain and task type
- execute_task: Main entry point for executing tasks with automatic routing
- execute_data_visualization: Generates data visualization charts
- Supports multiple output formats: image, docx, xlsx, pdf

Research & Plan Workflow (Autonomy Core):
- ContextExtractor: Analyzes uploaded files (PDF/Excel) to extract context
- WorkPlanGenerator: Creates a detailed work plan before execution
- PlanExecutor: Executes the work plan in the E2B sandbox
- PlanReviewer: Validates the output against the work plan
- ResearchAndPlanOrchestrator: Coordinates all four steps
"""

from .executor import (
    execute_task,
    execute_data_visualization,
    execute_data_visualization_simple,
    TaskRouter,
    TaskType,
    OutputFormat,
)

# Research & Plan Workflow exports
from .planning import (
    ResearchAndPlanOrchestrator,
    create_research_plan_workflow,
    ContextExtractor,
    WorkPlanGenerator,
    PlanExecutor,
    PlanReviewer,
)

__all__ = [
    # Executor exports
    "execute_task",
    "execute_data_visualization",
    "execute_data_visualization_simple",
    "TaskRouter",
    "TaskType",
    "OutputFormat",
    # Planning exports
    "ResearchAndPlanOrchestrator",
    "create_research_plan_workflow",
    "ContextExtractor",
    "WorkPlanGenerator",
    "PlanExecutor",
    "PlanReviewer",
]
