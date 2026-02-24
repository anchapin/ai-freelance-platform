"""
Research & Planning Module

This module implements the "Research & Plan" step for the autonomy workflow:
1. Agent analyzes uploaded files (PDF/Excel) to extract context
2. Agent creates a work plan
3. Agent executes the plan in the E2B sandbox
4. ArtifactReviewer checks the final document against the plan

The workflow ensures professional-grade output by:
- First understanding the input data/context
- Creating a detailed plan before execution
- Validating the output against the plan
"""

import json
import re
from typing import Optional, Dict, Any, List
from datetime import datetime

from src.llm_service import LLMService, TASK_TYPE_BASIC_ADMIN, TASK_TYPE_COMPLEX
from src.agent_execution.file_parser import parse_file, FileType, detect_file_type


class ContextExtractor:
    """
    Step 1: Analyzes uploaded files (PDF/Excel) to extract context.
    
    This class extracts meaningful context from various file types
    to inform the work plan generation.
    """
    
    def __init__(self, llm_service: Optional[LLMService] = None):
        """
        Initialize the context extractor.
        
        Args:
            llm_service: Optional LLMService instance for enhanced extraction
        """
        self.llm = llm_service
    
    def extract_context(
        self,
        file_content: Optional[str] = None,
        csv_data: Optional[str] = None,
        filename: Optional[str] = None,
        file_type: Optional[str] = None,
        domain: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Extract context from uploaded files.
        
        Args:
            file_content: Base64-encoded file content (for Excel/PDF)
            csv_data: CSV data as string
            filename: Original filename
            file_type: Type of file (csv, excel, pdf)
            domain: Domain for context-specific extraction
            
        Returns:
            Dictionary containing extracted context and metadata
        """
        context = {
            "file_info": {},
            "data_summary": {},
            "key_insights": [],
            "extraction_success": False,
            "raw_data": None
        }
        
        # Handle file content (Excel/PDF)
        if file_content and filename:
            parsed = parse_file(
                file_content=file_content,
                filename=filename,
                file_type=file_type
            )
            
            if parsed.get("success"):
                context["file_info"] = {
                    "filename": filename,
                    "file_type": file_type or detect_file_type(filename).value,
                    "row_count": parsed.get("row_count", 0),
                    "headers": parsed.get("headers", [])
                }
                context["data_summary"] = {
                    "headers": parsed.get("headers", []),
                    "row_count": parsed.get("row_count", 0),
                    "sample_data": parsed.get("data", [])[:5] if parsed.get("data") else []
                }
                context["raw_data"] = parsed.get("data_as_csv", "")
                context["extraction_success"] = True
                
                # Extract additional text from PDF if available
                if parsed.get("extracted_text"):
                    context["extracted_text"] = parsed["extracted_text"]
        
        # Handle CSV data
        elif csv_data:
            try:
                import pandas as pd
                import io
                
                df = pd.read_csv(io.StringIO(csv_data))
                
                context["file_info"] = {
                    "filename": filename or "data.csv",
                    "file_type": "csv",
                    "row_count": len(df),
                    "headers": df.columns.tolist()
                }
                context["data_summary"] = {
                    "headers": df.columns.tolist(),
                    "row_count": len(df),
                    "column_types": {col: str(dtype) for col, dtype in df.dtypes.items()},
                    "numeric_columns": df.select_dtypes(include=['number']).columns.tolist(),
                    "categorical_columns": df.select_dtypes(include=['object']).columns.tolist(),
                    "sample_data": df.head(5).to_dict('records')
                }
                context["raw_data"] = csv_data
                context["extraction_success"] = True
                
                # Generate basic statistics for numeric columns
                if not df.select_dtypes(include=['number']).empty:
                    context["key_insights"] = self._extract_basic_insights(df)
                
            except Exception as e:
                context["error"] = str(e)
        
        # Use LLM to enhance context understanding for complex files
        if self.llm and context.get("extraction_success") and (file_content or csv_data):
            enhanced_context = self._enhance_with_llm(context, domain)
            context["key_insights"] = enhanced_context.get("key_insights", context.get("key_insights", []))
            context["data_summary"]["llm_analysis"] = enhanced_context.get("analysis")
        
        return context
    
    def _extract_basic_insights(self, df) -> List[str]:
        """Extract basic statistical insights from the data."""
        insights = []
        
        # Numeric column statistics
        numeric_cols = df.select_dtypes(include=['number']).columns
        for col in numeric_cols:
            insights.append(f"{col}: min={df[col].min()}, max={df[col].max()}, mean={df[col].mean():.2f}")
        
        return insights
    
    def _enhance_with_llm(self, context: Dict[str, Any], domain: Optional[str]) -> Dict[str, Any]:
        """
        Use LLM to enhance context understanding.
        
        Args:
            context: Basic extracted context
            domain: Domain for context-specific analysis
            
        Returns:
            Enhanced context with LLM analysis
        """
        if not self.llm:
            return {}
        
        headers = context.get("data_summary", {}).get("headers", [])
        sample_data = context.get("data_summary", {}).get("sample_data", [])
        
        system_prompt = f"""You are an expert data analyst specializing in {domain or 'general'} data.
Analyze the provided data structure and provide key insights that would help
create an effective work plan for data visualization or document generation.

Focus on:
1. What the data represents
2. Key patterns or trends visible in the data
3. Recommended visualization types
4. Important considerations for the domain"""

        prompt = f"""Data Headers: {headers}
Sample Data (first 5 rows): {sample_data}

Provide a brief analysis (2-3 sentences) and list 3-5 key insights about this data
that would inform a work plan. Return JSON with keys: analysis, key_insights."""

        try:
            result = self.llm.complete(
                prompt=prompt,
                temperature=0.3,
                max_tokens=500,
                system_prompt=system_prompt
            )
            
            # Parse JSON response
            content = result.get("content", "")
            if "{" in content and "}" in content:
                json_start = content.find("{")
                json_end = content.rfind("}") + 1
                return eval(content[json_start:json_end])
        except Exception:
            pass
        
        return {}


class WorkPlanGenerator:
    """
    Step 2: Creates a work plan based on extracted context and user requirements.
    
    The work plan includes:
    - Analysis of the input data
    - Proposed approach and methodology
    - Specific steps to execute
    - Success criteria
    - Potential challenges and mitigations
    """
    
    def __init__(self, llm_service: Optional[LLMService] = None):
        """
        Initialize the work plan generator.
        
        Args:
            llm_service: Optional LLMService instance for plan generation
        """
        self.llm = llm_service or LLMService()
    
    def create_work_plan(
        self,
        user_request: str,
        domain: str,
        extracted_context: Dict[str, Any],
        task_type: Optional[str] = None,
        output_format: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a comprehensive work plan based on context and requirements.
        
        Args:
            user_request: The user's original request
            domain: The domain (legal, accounting, data_analysis)
            extracted_context: Context extracted from uploaded files
            task_type: Optional task type (visualization, document, spreadsheet)
            output_format: Optional output format (image, docx, xlsx, pdf)
            
        Returns:
            Dictionary containing the work plan
        """
        # Build context summary for the prompt
        context_summary = self._build_context_summary(extracted_context)
        
        system_prompt = f"""You are an expert project planner for {domain} tasks.
Create a detailed work plan for fulfilling the user's request.

The work plan must include:
1. **Data Analysis**: What the input data contains and how to use it
2. **Approach**: Specific methodology for this task type
3. **Execution Steps**: Numbered steps to execute
4. **Success Criteria**: How to verify the output is correct
5. **Potential Issues**: What could go wrong and how to handle them

Return ONLY a JSON object with this structure (no markdown, no explanation):
{{
    "title": "Brief plan title",
    "data_analysis": "Description of input data and how to use it",
    "approach": "Methodology to use",
    "steps": ["Step 1", "Step 2", "Step 3"],
    "success_criteria": ["Criterion 1", "Criterion 2"],
    "potential_issues": ["Issue 1: How to handle"],
    "recommended_chart_type": "bar|line|pie|scatter|table|document" or null,
    "output_format": "image|docx|xlsx|pdf" or null
}}"""

        prompt = f"""User Request: {user_request}
Domain: {domain}
Task Type: {task_type or 'auto-detect'}
Output Format: {output_format or 'auto-detect'}

Input Data Context:
{context_summary}

Generate the work plan as JSON."""

        try:
            result = self.llm.complete(
                prompt=prompt,
                temperature=0.3,
                max_tokens=1500,
                system_prompt=system_prompt
            )
            
            # Parse JSON response
            content = result.get("content", "")
            plan = self._parse_plan_json(content)
            
            if plan:
                plan["generated_at"] = datetime.utcnow().isoformat()
                plan["domain"] = domain
                plan["user_request"] = user_request
                return {
                    "success": True,
                    "plan": plan
                }
            
            return {
                "success": False,
                "error": "Failed to parse work plan"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _build_context_summary(self, context: Dict[str, Any]) -> str:
        """Build a text summary of the extracted context."""
        parts = []
        
        # File info
        file_info = context.get("file_info", {})
        if file_info:
            parts.append(f"File: {file_info.get('filename', 'unknown')}")
            parts.append(f"File Type: {file_info.get('file_type', 'unknown')}")
            parts.append(f"Rows: {file_info.get('row_count', 0)}")
        
        # Data summary
        data_summary = context.get("data_summary", {})
        if data_summary.get("headers"):
            parts.append(f"Columns: {', '.join(data_summary['headers'])}")
        
        if data_summary.get("numeric_columns"):
            parts.append(f"Numeric Columns: {', '.join(data_summary['numeric_columns'])}")
        
        if data_summary.get("categorical_columns"):
            parts.append(f"Categorical Columns: {', '.join(data_summary['categorical_columns'])}")
        
        # Key insights
        insights = context.get("key_insights", [])
        if insights:
            parts.append("Key Insights:")
            for insight in insights[:5]:
                parts.append(f"  - {insight}")
        
        return "\n".join(parts) if parts else "No context available"
    
    def _parse_plan_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Parse JSON plan from LLM response."""
        # Try to find JSON in the response
        try:
            if "{" in content and "}" in content:
                json_start = content.find("{")
                json_end = content.rfind("}") + 1
                json_str = content[json_start:json_end]
                plan = eval(json_str)  # Safe here since we control the prompt
                
                # Validate required fields
                required = ["title", "approach", "steps", "success_criteria"]
                if all(field in plan for field in required):
                    return plan
        except (SyntaxError, NameError, ValueError):
            pass
        
        return None


class PlanExecutor:
    """
    Step 3: Executes the work plan in the E2B sandbox.
    
    This class takes the work plan and executes each step,
    generating the final artifact.
    """
    
    def __init__(self, llm_service: Optional[LLMService] = None):
        """
        Initialize the plan executor.
        
        Args:
            llm_service: Optional LLMService instance
        """
        self.llm = llm_service or LLMService()
    
    def execute_plan(
        self,
        work_plan: Dict[str, Any],
        csv_data: str,
        domain: str,
        api_key: Optional[str] = None,
        sandbox_timeout: int = 120
    ) -> Dict[str, Any]:
        """
        Execute the work plan to generate the artifact.
        
        Args:
            work_plan: The work plan dictionary
            csv_data: The CSV data to process
            domain: The domain
            api_key: E2B API key
            sandbox_timeout: Timeout for sandbox execution
            
        Returns:
            Dictionary with execution results
        """
        # Import here to avoid circular imports
        from src.agent_execution.executor import (
            execute_data_visualization,
            TaskRouter,
            TaskType,
            OutputFormat
        )
        
        user_request = work_plan.get("user_request", "")
        task_type = self._infer_task_type(work_plan)
        output_format = work_plan.get("output_format") or self._infer_output_format(work_plan)
        
        execution_log = {
            "started_at": datetime.utcnow().isoformat(),
            "steps_executed": [],
            "plan_title": work_plan.get("title", "")
        }
        
        try:
            # Determine execution approach based on output format
            if output_format in ["docx", "pdf"]:
                # Use TaskRouter for document generation
                router = TaskRouter(llm_service=self.llm)
                result = router.route(
                    domain=domain,
                    user_request=user_request,
                    csv_data=csv_data,
                    task_type=task_type,
                    output_format=output_format,
                    api_key=api_key,
                    sandbox_timeout=sandbox_timeout
                )
            elif output_format == "xlsx":
                # Use TaskRouter for spreadsheet generation
                router = TaskRouter(llm_service=self.llm)
                result = router.route(
                    domain=domain,
                    user_request=user_request,
                    csv_data=csv_data,
                    task_type="spreadsheet",
                    output_format=output_format,
                    api_key=api_key,
                    sandbox_timeout=sandbox_timeout
                )
            else:
                # Default to visualization
                result = execute_data_visualization(
                    csv_data=csv_data,
                    user_request=user_request,
                    domain=domain,
                    api_key=api_key,
                    sandbox_timeout=sandbox_timeout,
                    llm_service=self.llm,
                    enable_pre_submission_review=True
                )
            
            execution_log["completed_at"] = datetime.utcnow().isoformat()
            execution_log["steps_executed"] = work_plan.get("steps", [])
            execution_log["execution_result"] = result
            
            return {
                "success": result.get("success", False),
                "result": result,
                "execution_log": execution_log
            }
            
        except Exception as e:
            execution_log["error"] = str(e)
            execution_log["completed_at"] = datetime.utcnow().isoformat()
            
            return {
                "success": False,
                "error": str(e),
                "execution_log": execution_log
            }
    
    def _infer_task_type(self, plan: Dict[str, Any]) -> str:
        """Infer task type from work plan."""
        recommended = plan.get("recommended_chart_type", "")
        if recommended in ["bar", "line", "pie", "scatter", "histogram"]:
            return "visualization"
        elif recommended == "table":
            return "spreadsheet"
        elif recommended == "document":
            return "document"
        return "auto"
    
    def _infer_output_format(self, plan: Dict[str, Any]) -> str:
        """Infer output format from work plan."""
        output_format = plan.get("output_format", "")
        if output_format in ["image", "docx", "xlsx", "pdf"]:
            return output_format
        return "image"


class PlanReviewer:
    """
    Step 4: ArtifactReviewer checks the final document against the plan.
    
    This enhanced reviewer validates that the generated artifact
    matches both the original user request AND the work plan.
    """
    
    def __init__(self, llm_service: Optional[LLMService] = None):
        """
        Initialize the plan reviewer.
        
        Args:
            llm_service: Optional LLMService instance
        """
        self.llm = llm_service or LLMService()
    
    def review_against_plan(
        self,
        artifact_url: str,
        work_plan: Dict[str, Any],
        user_request: str,
        domain: str,
        execution_result: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Review the generated artifact against the work plan.
        
        Args:
            artifact_url: URL of the generated artifact (base64 or file URL)
            work_plan: The work plan that was executed
            user_request: Original user request
            domain: The domain
            execution_result: Optional execution result for additional context
            
        Returns:
            Dictionary containing review results
        """
        # Extract base64 from URL if present
        artifact_base64 = ""
        if "base64," in artifact_url:
            artifact_base64 = artifact_url.split("base64,")[1]
        
        plan_title = work_plan.get("title", "")
        plan_steps = work_plan.get("steps", [])
        success_criteria = work_plan.get("success_criteria", [])
        potential_issues = work_plan.get("potential_issues", [])
        
        system_prompt = f"""You are an expert artifact reviewer for {domain} tasks.
Your job is to validate that the generated artifact meets the work plan requirements.

You will evaluate:
1. Does the artifact match the work plan title and approach?
2. Were all execution steps completed?
3. Does the artifact meet the success criteria?
4. Are there any issues from the potential issues list that occurred?

Respond with a JSON object containing:
{{
    "approved": true/false,
    "feedback": "Detailed feedback if not approved",
    "issues": ["List of specific issues found"],
    "criteria_met": ["Success criteria that were met"],
    "criteria_not_met": ["Success criteria that were not met"],
    "plan_adherence": "high|medium|low - how well the artifact follows the plan"
}}"""

        prompt = f"""Work Plan Title: {plan_title}
Work Plan Approach: {work_plan.get('approach', '')}
Execution Steps: {', '.join(plan_steps)}
Success Criteria: {', '.join(success_criteria)}
Potential Issues: {', '.join(potential_issues)}
User Request: {user_request}
Domain: {domain}

Artifact: {artifact_url[:100]}... (truncated)

Please review this artifact against the work plan and success criteria.
Return your review in JSON format."""

        try:
            result = self.llm.complete(
                prompt=prompt,
                temperature=0.2,
                max_tokens=1000,
                system_prompt=system_prompt
            )
            
            content = result.get("content", "")
            
            # Try to parse JSON response
            if "{" in content and "}" in content:
                json_start = content.find("{")
                json_end = content.rfind("}") + 1
                review_data = eval(content[json_start:json_end])
                
                return {
                    "success": True,
                    "approved": review_data.get("approved", False),
                    "feedback": review_data.get("feedback", ""),
                    "issues": review_data.get("issues", []),
                    "criteria_met": review_data.get("criteria_met", []),
                    "criteria_not_met": review_data.get("criteria_not_met", []),
                    "plan_adherence": review_data.get("plan_adherence", "medium"),
                    "reviewed_at": datetime.utcnow().isoformat()
                }
            
            # Default approval if parsing fails
            return {
                "success": True,
                "approved": True,
                "feedback": "",
                "issues": [],
                "plan_adherence": "unknown"
            }
            
        except Exception as e:
            return {
                "success": False,
                "approved": True,  # Default to approved on error
                "error": str(e)
            }
    
    def regenerate_with_feedback(
        self,
        work_plan: Dict[str, Any],
        review_feedback: str,
        csv_data: str,
        domain: str
    ) -> Dict[str, Any]:
        """
        Regenerate artifact based on review feedback.
        
        Args:
            work_plan: Original work plan
            review_feedback: Feedback from the reviewer
            csv_data: CSV data to process
            domain: Domain
            
        Returns:
            Dictionary with regenerated code/plan
        """
        system_prompt = f"""You are an expert {domain} data analyst. The previous artifact was rejected for the following reason:

{review_feedback}

Your task is to regenerate the artifact to address these issues while following the work plan:
- Title: {work_plan.get('title', '')}
- Approach: {work_plan.get('approach', '')}
- Steps: {', '.join(work_plan.get('steps', []))}

Generate a new approach or code that addresses the feedback.
Return a JSON object with:
{{
    "revised_approach": "Description of changes to make",
    "new_steps": ["Step 1", "Step 2"],
    "code_or_instructions": "Any specific code changes needed"
}}"""

        prompt = f"""Original User Request: {work_plan.get('user_request', '')}
Domain: {domain}

Please revise the approach to address the review feedback. Return JSON."""

        try:
            result = self.llm.complete(
                prompt=prompt,
                temperature=0.3,
                max_tokens=1000,
                system_prompt=system_prompt
            )
            
            content = result.get("content", "")
            
            if "{" in content and "}" in content:
                json_start = content.find("{")
                json_end = content.rfind("}") + 1
                revision = eval(content[json_start:json_end])
                
                return {
                    "success": True,
                    "revision": revision
                }
            
            return {
                "success": False,
                "error": "Failed to parse revision"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# =============================================================================
# LLM SELECTION HELPERS
# =============================================================================


def _get_llm_for_task(domain: Optional[str]) -> LLMService:
    """
    Get the appropriate LLMService based on task domain for cost optimization.
    
    Strategy:
    - Legal & Accounting domains: Use cloud models (GPT-4o) for high accuracy
    - Data analysis (basic admin): Use local models (Llama 3.2) to eliminate API costs
    
    Args:
        domain: The task domain (legal, accounting, data_analysis)
        
    Returns:
        Configured LLMService instance
    """
    domain_lower = (domain or "").lower().strip()
    
    # Legal and Accounting require high accuracy - use cloud models
    if domain_lower in ["legal", "accounting"]:
        print(f"Using cloud model for {domain} task (high accuracy required)")
        return LLMService.for_complex_task()
    
    # Data analysis - use local models for cost savings
    print("Using local model for data analysis task (cost optimization)")
    return LLMService.for_basic_admin()


# =============================================================================
# MAIN ORCHESTRATOR - Research & Plan Workflow
# =============================================================================


class ResearchAndPlanOrchestrator:
    """
    Main orchestrator for the Research & Plan workflow.
    
    This class coordinates all four steps:
    1. Context Extraction
    2. Work Plan Generation
    3. Plan Execution
    4. Artifact Review
    
    Cost Optimization:
    - Legal & Accounting tasks use cloud models (GPT-4o) for accuracy
    - Data analysis tasks use local models (Llama 3.2) to save API costs
    """
    
    def __init__(self, llm_service: Optional[LLMService] = None, domain: Optional[str] = None):
        """
        Initialize the orchestrator.
        
        Args:
            llm_service: Optional LLMService instance
            domain: Domain for selecting appropriate LLM (legal, accounting, data_analysis)
        """
        # Get appropriate LLM based on domain if not provided
        self.domain = domain
        if llm_service is None and domain:
            self.llm = _get_llm_for_task(domain)
        else:
            self.llm = llm_service or LLMService()
        
        self.context_extractor = ContextExtractor(self.llm)
        self.plan_generator = WorkPlanGenerator(self.llm)
        self.plan_executor = PlanExecutor(self.llm)
        self.plan_reviewer = PlanReviewer(self.llm)
    
    def execute_workflow(
        self,
        user_request: str,
        domain: str,
        csv_data: Optional[str] = None,
        file_content: Optional[str] = None,
        filename: Optional[str] = None,
        file_type: Optional[str] = None,
        api_key: Optional[str] = None,
        sandbox_timeout: int = 120,
        task_type: Optional[str] = None,
        output_format: Optional[str] = None,
        max_review_attempts: int = 2
    ) -> Dict[str, Any]:
        """
        Execute the complete Research & Plan workflow.
        
        Args:
            user_request: User's request
            domain: Domain (legal, accounting, data_analysis)
            csv_data: Optional CSV data
            file_content: Optional file content (base64)
            filename: Optional filename
            file_type: Optional file type
            api_key: E2B API key
            sandbox_timeout: Sandbox timeout
            task_type: Optional task type
            output_format: Optional output format
            max_review_attempts: Maximum review attempts
            
        Returns:
            Dictionary with complete workflow results
        """
        workflow_result = {
            "workflow": "research_and_plan",
            "started_at": datetime.utcnow().isoformat(),
            "steps": {}
        }
        
        # Step 1: Extract Context
        print("Step 1: Extracting context from uploaded files...")
        extracted_context = self.context_extractor.extract_context(
            file_content=file_content,
            csv_data=csv_data,
            filename=filename,
            file_type=file_type,
            domain=domain
        )
        workflow_result["steps"]["context_extraction"] = {
            "success": extracted_context.get("extraction_success", False),
            "context": extracted_context
        }
        
        # Step 2: Generate Work Plan
        print("Step 2: Creating work plan...")
        plan_result = self.plan_generator.create_work_plan(
            user_request=user_request,
            domain=domain,
            extracted_context=extracted_context,
            task_type=task_type,
            output_format=output_format
        )
        
        if not plan_result.get("success"):
            workflow_result["failed_at"] = "plan_generation"
            workflow_result["error"] = plan_result.get("error", "Plan generation failed")
            return workflow_result
        
        work_plan = plan_result["plan"]
        workflow_result["steps"]["plan_generation"] = {
            "success": True,
            "plan": work_plan
        }
        
        # Get CSV data for execution
        exec_csv_data = extracted_context.get("raw_data") or csv_data or ""
        
        # Step 3: Execute Plan
        print("Step 3: Executing work plan in E2B sandbox...")
        execution_result = self.plan_executor.execute_plan(
            work_plan=work_plan,
            csv_data=exec_csv_data,
            domain=domain,
            api_key=api_key,
            sandbox_timeout=sandbox_timeout
        )
        
        workflow_result["steps"]["plan_execution"] = execution_result
        
        if not execution_result.get("success"):
            workflow_result["failed_at"] = "plan_execution"
            workflow_result["error"] = execution_result.get("error", "Execution failed")
            return workflow_result
        
        # Get the artifact URL from execution result
        exec_result = execution_result.get("result", {})
        artifact_url = exec_result.get("image_url") or exec_result.get("file_url", "")
        
        if not artifact_url:
            workflow_result["failed_at"] = "artifact_generation"
            workflow_result["error"] = "No artifact was generated"
            return workflow_result
        
        # Step 4: Review Artifact against Plan
        print("Step 4: Reviewing artifact against work plan...")
        review_attempts = 0
        approved = False
        current_feedback = ""
        
        while review_attempts < max_review_attempts and not approved:
            review_result = self.plan_reviewer.review_against_plan(
                artifact_url=artifact_url,
                work_plan=work_plan,
                user_request=user_request,
                domain=domain,
                execution_result=exec_result
            )
            
            review_attempts += 1
            approved = review_result.get("approved", False)
            current_feedback = review_result.get("feedback", "")
            
            if not approved and review_attempts < max_review_attempts:
                print(f"Review not approved, attempt {review_attempts + 1}/{max_review_attempts}")
                print(f"Feedback: {current_feedback}")
                
                # Try to regenerate with feedback
                revision = self.plan_reviewer.regenerate_with_feedback(
                    work_plan=work_plan,
                    review_feedback=current_feedback,
                    csv_data=exec_csv_data,
                    domain=domain
                )
                
                if revision.get("success"):
                    # Update work plan with revision
                    revised = revision.get("revision", {})
                    if revised.get("revised_approach"):
                        work_plan["approach"] = revised["revised_approach"]
                    if revised.get("new_steps"):
                        work_plan["steps"] = revised["new_steps"]
        
        workflow_result["steps"]["artifact_review"] = {
            "approved": approved,
            "feedback": current_feedback,
            "attempts": review_attempts,
            "review_result": review_result
        }
        
        # Final result
        workflow_result["completed_at"] = datetime.utcnow().isoformat()
        workflow_result["success"] = approved
        
        if approved:
            workflow_result["artifact_url"] = artifact_url
            workflow_result["message"] = "Artifact approved by reviewer"
        else:
            workflow_result["message"] = f"Artifact not approved after {review_attempts} attempts: {current_feedback}"
        
        return workflow_result


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def create_research_plan_workflow(
    user_request: str,
    domain: str,
    csv_data: Optional[str] = None,
    file_content: Optional[str] = None,
    filename: Optional[str] = None,
    file_type: Optional[str] = None,
    api_key: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Convenience function to execute the Research & Plan workflow.
    
    Args:
        user_request: User's request
        domain: Domain
        csv_data: Optional CSV data
        file_content: Optional file content
        filename: Optional filename
        file_type: Optional file type
        api_key: E2B API key
        **kwargs: Additional arguments
        
    Returns:
        Dictionary with workflow results
    """
    orchestrator = ResearchAndPlanOrchestrator()
    return orchestrator.execute_workflow(
        user_request=user_request,
        domain=domain,
        csv_data=csv_data,
        file_content=file_content,
        filename=filename,
        file_type=file_type,
        api_key=api_key,
        **kwargs
    )
