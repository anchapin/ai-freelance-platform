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

# Lazy imports to avoid circular dependencies
def __getattr__(name):
    """Lazy load modules to avoid circular imports."""
    if name == "execute_task":
        from .executor import execute_task
        return execute_task
    elif name == "execute_data_visualization":
        from .executor import execute_data_visualization
        return execute_data_visualization
    elif name == "execute_data_visualization_simple":
        from .executor import execute_data_visualization_simple
        return execute_data_visualization_simple
    elif name == "TaskRouter":
        from .executor import TaskRouter
        return TaskRouter
    elif name == "TaskType":
        from .executor import TaskType
        return TaskType
    elif name == "OutputFormat":
        from .executor import OutputFormat
        return OutputFormat
    elif name == "ResearchAndPlanOrchestrator":
        from .planning import ResearchAndPlanOrchestrator
        return ResearchAndPlanOrchestrator
    elif name == "create_research_plan_workflow":
        from .planning import create_research_plan_workflow
        return create_research_plan_workflow
    elif name == "ContextExtractor":
        from .planning import ContextExtractor
        return ContextExtractor
    elif name == "WorkPlanGenerator":
        from .planning import WorkPlanGenerator
        return WorkPlanGenerator
    elif name == "PlanExecutor":
        from .planning import PlanExecutor
        return PlanExecutor
    elif name == "PlanReviewer":
        from .planning import PlanReviewer
        return PlanReviewer
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

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
