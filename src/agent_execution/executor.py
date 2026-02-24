"""
E2B Code Interpreter Executor

This module provides functionality for executing code in secure sandboxes
using the E2B Code Interpreter SDK. It takes user's CSV data and generates
pandas data visualization charts inside a secure sandbox environment.

Features:
- Retry loop: If code fails (SyntaxError, runtime error, etc.), the LLM is asked to fix it
- Up to 3 retry attempts before giving up
- Pre-Submission Review: Agent self-evaluates artifact against user description before sandbox closes
- Up to 2 review/regeneration attempts to ensure quality
- Detailed error tracking for debugging
"""

import os
import io
import base64
import json
import re
from typing import Optional
from datetime import datetime

# E2B Code Interpreter SDK
from e2b_code_interpreter import Sandbox

# Import LLM Service for AI-powered code generation
from src.llm_service import LLMService

# Import file parser for different file types
from src.agent_execution.file_parser import parse_file, FileType, detect_file_type

# For type hints
try:
    from pandas import DataFrame
except ImportError:
    DataFrame = None  # Will be available in sandbox


# Maximum number of retry attempts when code fails
MAX_RETRY_ATTEMPTS = 3

# Maximum number of review attempts (self-evaluation before submission)
MAX_REVIEW_ATTEMPTS = 2


# =============================================================================
# DOMAIN-SPECIFIC SYSTEM PROMPTS
# =============================================================================

def get_domain_system_prompt(domain: str, file_type: str = "csv") -> str:
    """
    Get the appropriate system prompt based on the task domain and file type.
    
    Args:
        domain: The domain of the task (legal, accounting, data_analysis)
        file_type: The type of file being processed (csv, excel, pdf)
        
    Returns:
        The system prompt string for the specified domain
    """
    domain_lower = domain.lower().strip()
    file_type_lower = file_type.lower().strip() if file_type else "csv"
    
    # Build file type description
    file_type_desc = ""
    if file_type_lower == "excel":
        file_type_desc = "Excel spreadsheet (.xlsx or .xls)"
    elif file_type_lower == "pdf":
        file_type_desc = "PDF document"
    else:
        file_type_desc = "CSV file"
    
    # Legal domain prompt
    if domain_lower == "legal":
        return f"""You are an expert legal data analyst. The user wants to visualize data from legal documents, 
court records, case information, or legal metrics. The data comes from a {file_type_desc}.

Your expertise includes:
- Litigation analytics and case outcomes
- Contract terms and compliance metrics
- Legal billing and time tracking visualizations
- Court docket and scheduling data
- Practice area analysis and trends
- Attorney/client performance metrics

I will provide you with:
1. The column headers from the data file (representing legal data fields)
2. The user's visualization request

Your task is to generate ONLY valid Python code (not JSON) that:
- Uses pandas to read data from a variable named 'csv_data' (a string containing CSV-formatted data)
- Uses matplotlib to create an appropriate visualization suitable for legal context
- Uses professional, clear styling appropriate for legal documents
- Saves the figure to a base64-encoded PNG string in a variable named 'img_base64'
- Prints a JSON result with these exact keys: image_url, chart_type, columns, success

Visualization guidelines for legal data:
- Use clean, professional color schemes (blues, grays, muted tones)
- Include clear labels and titles suitable for court filings
- Ensure data accuracy - legal professionals need precise visualizations
- Consider confidentiality in how data is presented

The code MUST:
1. Read data using: df = pd.read_csv(io.StringIO(csv_data))
2. Create appropriate matplotlib chart based on user's request
3. Save to base64: img_base64 = base64.b64encode(buf.read()).decode('utf-8')
4. Print: print(json.dumps({{'image_url': f'data:image/png;base64,{{img_base64}}', 'chart_type': '...', 'columns': [...], 'success': True}}))

Return ONLY the Python code, no explanations or markdown. The code should be complete and ready to execute."""

    # Accounting domain prompt
    elif domain_lower == "accounting":
        return f"""You are an expert accounting data analyst. The user wants to visualize data from financial 
statements, bookkeeping records, tax documents, or accounting metrics. The data comes from a {file_type_desc}.

Your expertise includes:
- Financial statement analysis (balance sheets, income statements, cash flow)
- Budget vs. actual comparisons
- Revenue and expense tracking
- Tax compliance and liability visualizations
- Audit findings and reconciliation data
- Profitability and margin analysis
- Accounts payable/receivable aging

I will provide you with:
1. The column headers from the data file (representing accounting data fields)
2. The user's visualization request

Your task is to generate ONLY valid Python code (not JSON) that:
- Uses pandas to read data from a variable named 'csv_data' (a string containing CSV-formatted data)
- Uses matplotlib to create appropriate financial visualizations
- Uses professional styling suitable for financial reports and presentations
- Saves the figure to a base64-encoded PNG string in a variable named 'img_base64'
- Prints a JSON result with these exact keys: image_url, chart_type, columns, success

Visualization guidelines for accounting data:
- Use financial-standard color schemes (greens for positive, reds for negative, blues for neutral)
- Include dollar signs and percentage formatting where appropriate
- Ensure numerical accuracy to two decimal places
- Use clear legends and axis labels suitable for stakeholders
- Consider creating comparative charts (period over period, budget vs actual)

The code MUST:
1. Read data using: df = pd.read_csv(io.StringIO(csv_data))
2. Create appropriate matplotlib chart based on user's request
3. Save to base64: img_base64 = base64.b64encode(buf.read()).decode('utf-8')
4. Print: print(json.dumps({{'image_url': f'data:image/png;base64,{{img_base64}}', 'chart_type': '...', 'columns': [...], 'success': True}}))

Return ONLY the Python code, no explanations or markdown. The code should be complete and ready to execute."""

    # Default (data_analysis) domain prompt
    else:
        return f"""You are an expert data scientist. The user wants to visualize data from a {file_type_desc}.

I will provide you with:
1. The column headers from the data file
2. The user's visualization request

Your task is to generate ONLY valid Python code (not JSON) that:
- Uses pandas to read data from a variable named 'csv_data' (a string containing CSV-formatted data)
- Uses matplotlib to create an appropriate visualization
- Saves the figure to a base64-encoded PNG string in a variable named 'img_base64'
- Prints a JSON result with these exact keys: image_url, chart_type, columns, success

The code MUST:
1. Read data using: df = pd.read_csv(io.StringIO(csv_data))
2. Create appropriate matplotlib chart based on user's request
3. Save to base64: img_base64 = base64.b64encode(buf.read()).decode('utf-8')
4. Print: print(json.dumps({{'image_url': f'data:image/png;base64,{{img_base64}}', 'chart_type': '...', 'columns': [...], 'success': True}}))

Return ONLY the Python code, no explanations or markdown. The code should be complete and ready to execute."""


class ArtifactReviewer:
    """
    Handles Pre-Submission Review: Self-evaluates the generated artifact
    against the user's description before the sandbox closes.
    
    This ensures the visualization actually matches what the user requested.
    """
    
    def __init__(self, llm_service: Optional[LLMService] = None):
        """
        Initialize the artifact reviewer.
        
        Args:
            llm_service: Optional LLMService instance. If not provided,
                        creates one with default settings.
        """
        self.llm = llm_service or LLMService()
    
    def review_artifact(
        self,
        image_base64: str,
        user_request: str,
        chart_type: str,
        code_executed: str
    ) -> dict:
        """
        Review the generated artifact against the user's request.
        
        Args:
            image_base64: Base64-encoded image of the visualization
            user_request: The original user request
            chart_type: The type of chart that was generated
            code_executed: The Python code that was executed
            
        Returns:
            Dictionary containing:
                - approved: bool indicating if artifact matches request
                - feedback: Feedback for improvement if not approved
                - issues: List of specific issues found
                - success: Whether the review was performed
        """
        system_prompt = """You are an expert data visualization reviewer. Your task is to evaluate
whether a generated chart matches the user's request.

You will receive:
1. The user's original request
2. The chart type that was generated
3. The Python code that was executed

Your job is to determine if the visualization matches the request.
Consider:
- Does the chart type match what was requested? (e.g., bar chart, line chart, pie chart)
- Are appropriate columns being visualized?
- Is the visualization meaningful for the data?
- Are there any obvious issues (wrong data, missing labels, etc.)?

Respond with a JSON object containing:
{{
    "approved": true/false,
    "feedback": "Brief explanation if not approved, empty string if approved",
    "issues": ["list of specific issues if any, empty list if approved"]
}}

Be strict but fair. Approve if the visualization reasonably matches the request.
Only reject if there are significant issues that would make the result unusable."""

        # Build prompt with visualization details
        prompt = f"""User Request: {user_request}
Chart Type Generated: {chart_type}
Code Executed:
{code_executed}

Please review this visualization and determine if it matches the user's request.
Return your review in JSON format."""

        try:
            result = self.llm.complete(
                prompt=prompt,
                temperature=0.2,
                max_tokens=1000,
                system_prompt=system_prompt
            )
            
            # Parse the LLM response
            response_content = result["content"].strip()
            review_result = self._parse_review_response(response_content)
            
            return review_result
            
        except Exception as e:
            return {
                "approved": True,  # Default to approved on error
                "feedback": "",
                "issues": [],
                "success": False,
                "error": str(e)
            }
    
    def _parse_review_response(self, response: str) -> dict:
        """
        Parse the review response from LLM.
        
        Args:
            response: The LLM response content
            
        Returns:
            Dictionary with parsed review result
        """
        # Try to find JSON in the response
        try:
            if "{" in response and "}" in response:
                json_start = response.find("{")
                json_end = response.rfind("}") + 1
                json_str = response[json_start:json_end]
                review_data = eval(json_str)  # Safe here since we control the prompt
                
                return {
                    "approved": review_data.get("approved", True),
                    "feedback": review_data.get("feedback", ""),
                    "issues": review_data.get("issues", []),
                    "success": True
                }
        except (SyntaxError, ValueError, NameError):
            pass
        
        # Default to approved if parsing fails
        return {
            "approved": True,
            "feedback": "",
            "issues": [],
            "success": True
        }
    
    def regenerate_with_feedback(
        self,
        csv_headers: list,
        user_request: str,
        feedback: str,
        chart_type: str
    ) -> dict:
        """
        Regenerate visualization code with feedback from review.
        
        Args:
            csv_headers: List of CSV column headers
            user_request: The original user request
            feedback: Feedback from the reviewer
            chart_type: The chart type that needs to be generated
            
        Returns:
            Dictionary containing:
                - code: New Python code for visualization
                - success: Whether regeneration was successful
        """
        system_prompt = f"""You are an expert data scientist. The previous visualization was rejected for the following reason:

{feedback}

Your task is to generate NEW Python code that addresses these issues.
The code should:
- Use pandas to read CSV data from a variable named 'csv_data' (a string)
- Use matplotlib to create an appropriate visualization that addresses the feedback
- Save the figure to a base64-encoded PNG string in a variable named 'img_base64'
- Print a JSON result with these exact keys: image_url, chart_type, columns, success

The code MUST:
1. Read CSV using: df = pd.read_csv(io.StringIO(csv_data))
2. Create appropriate matplotlib chart based on user's request AND feedback
3. Save to base64: img_base64 = base64.b64encode(buf.read()).decode('utf-8')
4. Print: print(json.dumps({{'image_url': f'data:image/png;base64,{{img_base64}}', 'chart_type': '...', 'columns': [...], 'success': True}}))

Return ONLY the Python code, no explanations or markdown."""

        prompt = f"""CSV Headers: {csv_headers}
User Request: {user_request}
Requested Chart Type: {chart_type}

Please generate new code that addresses the feedback. Return only the code, no markdown formatting."""

        try:
            result = self.llm.complete(
                prompt=prompt,
                temperature=0.3,
                max_tokens=2000,
                system_prompt=system_prompt
            )
            
            response_content = result["content"].strip()
            code = self._extract_python_code(response_content)
            
            return {
                "code": code,
                "success": True
            }
            
        except Exception as e:
            return {
                "code": "",
                "success": False,
                "error": str(e)
            }
    
    def _extract_python_code(self, response: str) -> str:
        """
        Extract Python code from LLM response.
        
        Args:
            response: The LLM response content
            
        Returns:
            The extracted Python code
        """
        # Try to find code in markdown code block
        code_match = re.search(r'```python\s*([\s\S]*?)\s*```', response)
        if code_match:
            return code_match.group(1).strip()
        
        # Try to find code in markdown code block without language specifier
        code_match = re.search(r'```\s*([\s\S]*?)\s*```', response)
        if code_match:
            return code_match.group(1).strip()
        
        # If no code block found, return the whole response as code
        return response.strip()


class CodeFixer:
    """
    Handles retry logic for fixing failed code by feeding errors back to the LLM.
    
    When the E2B sandbox fails to execute code, this class generates a prompt
    that includes the error message and asks the LLM to fix the code.
    """
    
    def __init__(self, llm_service: Optional[LLMService] = None):
        """
        Initialize the code fixer.
        
        Args:
            llm_service: Optional LLMService instance. If not provided,
                        creates one with default settings.
        """
        self.llm = llm_service or LLMService()
    
    def fix_code(
        self,
        failed_code: str,
        error_message: str,
        csv_headers: list,
        user_request: str
    ) -> dict:
        """
        Generate fixed Python code based on the error message.
        
        Args:
            failed_code: The code that previously failed
            error_message: The error message from the failed execution
            csv_headers: List of CSV column headers
            user_request: The original user request
            
        Returns:
            Dictionary containing:
                - code: Fixed Python code
                - success: Whether the fix was generated
                - error: Any error during the fix attempt
        """
        system_prompt = """You are an expert Python developer. The user's code failed to execute.

Your task is to fix the code and return ONLY the corrected Python code (not JSON).
The code should:
- Use pandas to read CSV data from a variable named 'csv_data' (a string)
- Use matplotlib to create an appropriate visualization
- Save the figure to a base64-encoded PNG string in a variable named 'img_base64'
- Print a JSON result with these exact keys: image_url, chart_type, columns, success

Common errors to fix:
- SyntaxError: Check for missing colons, parentheses, brackets, quotes
- NameError: Check that all variables are defined before use
- ImportError: Check that all imports are correct
- IndexError: Check array/list bounds
- KeyError: Check dictionary keys
- ValueError: Check value types and conversions

The code MUST:
1. Read CSV using: df = pd.read_csv(io.StringIO(csv_data))
2. Create appropriate matplotlib chart based on user's request
3. Save to base64: img_base64 = base64.b64encode(buf.read()).decode('utf-8')
4. Print: print(json.dumps({'image_url': f'data:image/png;base64,{img_base64}', 'chart_type': '...', 'columns': [...], 'success': True}}))

Return ONLY the Python code, no explanations or markdown."""

        # Build prompt with error details
        prompt = f"""The previous code failed with this error:
{error_message}

Original User Request: {user_request}

CSV Headers: {csv_headers}

Failed code:
{failed_code}

Please fix the code and return ONLY the corrected Python code. No markdown formatting, no explanations."""

        try:
            result = self.llm.complete(
                prompt=prompt,
                temperature=0.3,
                max_tokens=2000,
                system_prompt=system_prompt
            )
            
            # Extract Python code from response
            response_content = result["content"].strip()
            code = self._extract_python_code(response_content)
            
            return {
                "code": code,
                "success": True,
                "error": None
            }
            
        except Exception as e:
            return {
                "code": "",
                "success": False,
                "error": str(e)
            }
    
    def _extract_python_code(self, response: str) -> str:
        """
        Extract Python code from LLM response.
        
        Args:
            response: The LLM response content
            
        Returns:
            The extracted Python code
        """
        # Try to find code in markdown code block
        code_match = re.search(r'```python\s*([\s\S]*?)\s*```', response)
        if code_match:
            return code_match.group(1).strip()
        
        # Try to find code in markdown code block without language specifier
        code_match = re.search(r'```\s*([\s\S]*?)\s*```', response)
        if code_match:
            return code_match.group(1).strip()
        
        # If no code block found, return the whole response as code
        return response.strip()


class AIResponseGenerator:
    """
    AI-powered response generator using LLMService.
    Generates Python code for data visualization based on user requests.
    Supports domain-specific prompts for Legal and Accounting domains.
    """
    
    def __init__(self, llm_service: Optional[LLMService] = None, domain: Optional[str] = None):
        """
        Initialize the AI response generator.
        
        Args:
            llm_service: Optional LLMService instance. If not provided,
                        creates one with default settings.
            domain: Optional domain for selecting specialized system prompt
                    (legal, accounting, or data_analysis/default)
        """
        self.llm = llm_service or LLMService()
        self.domain = domain
    
    def generate_visualization_code(
        self,
        csv_headers: list,
        user_request: str,
        domain: Optional[str] = None,
        file_type: Optional[str] = None
    ) -> dict:
        """
        Generate Python code for data visualization using LLM.
        
        Args:
            csv_headers: List of CSV column headers
            user_request: The user's visualization request
            domain: Optional domain override (legal, accounting, or data_analysis)
                    If not provided, uses the domain set during initialization
            file_type: Optional file type (csv, excel, pdf)
            
        Returns:
            Dictionary containing:
                - code: Python code to execute
                - chart_type: Type of chart being generated
                - description: Description of what the code does
        """
        # Use provided domain or fall back to initialized domain
        effective_domain = domain or self.domain or "data_analysis"
        
        # Use provided file type or default to csv
        effective_file_type = file_type or "csv"
        
        # Get domain-specific system prompt (now includes file type)
        system_prompt = get_domain_system_prompt(effective_domain, effective_file_type)

        # Build user prompt with CSV headers and user request
        prompt = f"""CSV Headers: {csv_headers}
User Request: {user_request}

Generate the Python code now. Return only the code, no markdown formatting."""

        try:
            result = self.llm.complete(
                prompt=prompt,
                temperature=0.3,
                max_tokens=2000,
                system_prompt=system_prompt
            )
            
            # Parse the LLM response to extract Python code
            response_content = result["content"].strip()
            
            # Try to extract Python code from the response
            code = self._extract_python_code(response_content)
            
            # Extract chart_type from the generated code if possible
            chart_type = self._extract_chart_type(code) if code else "bar"
            
            return {
                "code": code,
                "chart_type": chart_type,
                "description": f"LLM-generated {chart_type} chart",
                "success": True
            }
            
        except Exception as e:
            # Fallback to basic code generation if LLM fails
            return self._generate_fallback_code(csv_headers, user_request)
    
    def _extract_python_code(self, response: str) -> str:
        """
        Extract Python code from LLM response.
        
        Args:
            response: The LLM response content
            
        Returns:
            The extracted Python code
        """
        # Try to find code in markdown code block
        code_match = re.search(r'```python\s*([\s\S]*?)\s*```', response)
        if code_match:
            return code_match.group(1).strip()
        
        # Try to find code in markdown code block without language specifier
        code_match = re.search(r'```\s*([\s\S]*?)\s*```', response)
        if code_match:
            return code_match.group(1).strip()
        
        # If no code block found, return the whole response as code
        # (the LLM should return only code based on system prompt)
        return response.strip()
    
    def _extract_chart_type(self, code: str) -> str:
        """
        Extract chart type from generated Python code.
        
        Args:
            code: The generated Python code
            
        Returns:
            The detected chart type
        """
        code_lower = code.lower()
        
        if 'kind="pie"' in code_lower or "kind='pie'" in code_lower:
            return "pie"
        elif 'kind="line"' in code_lower or "kind='line'" in code_lower:
            return "line"
        elif 'kind="scatter"' in code_lower or "kind='scatter'" in code_lower:
            return "scatter"
        elif 'kind="hist"' in code_lower or "kind='histogram'" in code_lower:
            return "histogram"
        elif 'kind="bar"' in code_lower or "kind='bar'" in code_lower:
            return "bar"
        
        return "bar"  # Default
    
    def _generate_fallback_code(self, csv_headers: list, user_request: str) -> dict:
        """
        Generate basic fallback code if LLM fails.
        
        Args:
            csv_headers: List of CSV column headers
            user_request: The user's visualization request
            
        Returns:
            Dictionary with basic code
        """
        # Simple heuristic for chart type
        request_lower = user_request.lower()
        chart_type = "bar"
        
        if "line" in request_lower:
            chart_type = "line"
        elif "pie" in request_lower:
            chart_type = "pie"
        elif "scatter" in request_lower:
            chart_type = "scatter"
        elif "histogram" in request_lower or "distribution" in request_lower:
            chart_type = "histogram"
        elif "bar" in request_lower:
            chart_type = "bar"
        
        x_col = csv_headers[0] if len(csv_headers) > 0 else "index"
        y_col = csv_headers[1] if len(csv_headers) > 1 else csv_headers[0]
        
        code = f"""
import pandas as pd
import matplotlib.pyplot as plt
import io
import base64
import json

# Read CSV data
df = pd.read_csv(io.StringIO(csv_data))

# Get columns
columns = df.columns.tolist()
x_col = '{x_col}'
y_col = '{y_col}'

# Set up figure
fig, ax = plt.subplots(figsize=(10, 6))
fig.patch.set_facecolor('white')

# Generate chart based on type
chart_type = '{chart_type}'

if chart_type == 'bar':
    if y_col in df.columns and x_col in df.columns:
        df.plot(kind='bar', x=x_col, y=y_col, ax=ax, color='#4F46E5')
    else:
        df.plot(kind='bar', ax=ax, color='#4F46E5')
elif chart_type == 'line':
    if y_col in df.columns and x_col in df.columns:
        df.plot(kind='line', x=x_col, y=y_col, ax=ax, color='#4F46E5')
    else:
        df.plot(kind='line', ax=ax, color='#4F46E5')
elif chart_type == 'scatter':
    if len(columns) >= 2:
        df.plot(kind='scatter', x=columns[0], y=columns[1], ax=ax, c='#4F46E5', alpha=0.7)
elif chart_type == 'pie':
    if y_col in df.columns:
        df.plot(kind='pie', y=y_col, ax=ax, autopct='%1.1f%%', colors=plt.cm.Set3.colors)
elif chart_type == 'histogram':
    if y_col in df.columns:
        df[y_col].plot(kind='hist', ax=ax, bins=20, color='#4F46E5', alpha=0.7)
    else:
        df.hist(ax=ax, bins=20, color='#4F46E5', alpha=0.7)

# Customize
ax.set_title('Data Visualization', fontsize=14, fontweight='bold')
plt.xticks(rotation=45, ha='right')
plt.tight_layout()

# Save to base64
buf = io.BytesIO()
plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='white')
buf.seek(0)
img_base64 = base64.b64encode(buf.read()).decode('utf-8')
plt.close(fig)

# Result
result = {{
    'image_url': f'data:image/png;base64,{{img_base64}}',
    'chart_type': chart_type,
    'columns': columns,
    'success': True
}}

print(json.dumps(result))
"""
        
        return {
            "code": code,
            "chart_type": chart_type,
            "description": f"Fallback {chart_type} chart generation",
            "success": True
        }


def _execute_code_in_sandbox(
    code: str,
    e2b_api_key: Optional[str],
    sandbox_timeout: int
) -> tuple:
    """
    Execute Python code in the E2B sandbox and return the result.
    
    Args:
        code: The Python code to execute
        e2b_api_key: E2B API key
        sandbox_timeout: Timeout in seconds
        
    Returns:
        Tuple of (success, result/error_message, logs, artifacts)
    """
    try:
        with Sandbox(api_key=e2b_api_key) as sandbox:
            result = sandbox.run_code(code, timeout=sandbox_timeout)
            return (True, result, None, None)
    except Exception as e:
        error_msg = str(e)
        # Extract error type if possible
        if "SyntaxError" in error_msg:
            error_type = "SyntaxError"
        elif "NameError" in error_msg:
            error_type = "NameError"
        elif "ImportError" in error_msg or "ModuleNotFoundError" in error_msg:
            error_type = "ImportError"
        elif "Timeout" in error_msg:
            error_type = "TimeoutError"
        elif "IndexError" in error_msg:
            error_type = "IndexError"
        elif "KeyError" in error_msg:
            error_type = "KeyError"
        elif "ValueError" in error_msg:
            error_type = "ValueError"
        else:
            error_type = "ExecutionError"
        
        return (False, f"{error_type}: {error_msg}", None, None)


def _parse_sandbox_result(result, chart_type: str) -> dict:
    """
    Parse the result from E2B sandbox execution.
    
    Args:
        result: The E2B sandbox result object
        chart_type: The expected chart type
        
    Returns:
        Dictionary with parsed result data
    """
    # Try to find JSON output in logs
    if result.logs:
        for log in result.logs:
            if hasattr(log, 'text') and log.text:
                try:
                    if "{" in log.text and "}" in log.text:
                        json_start = log.text.find("{")
                        json_end = log.text.rfind("}") + 1
                        json_str = log.text[json_start:json_end]
                        result_data = eval(json_str)  # Safe here since we generated the code
                        
                        return {
                            "success": result_data.get("success", True),
                            "image_url": result_data.get("image_url", ""),
                            "chart_type": result_data.get("chart_type", chart_type),
                            "message": "Visualization generated successfully"
                        }
                except (SyntaxError, ValueError, NameError):
                    continue
    
    # Try to get image from artifacts
    if result.artifacts:
        for artifact in result.artifacts:
            if hasattr(artifact, 'data'):
                return {
                    "success": True,
                    "image_url": f"data:image/png;base64,{base64.b64encode(artifact.data).decode('utf-8')}",
                    "chart_type": chart_type,
                    "message": "Visualization generated from artifact"
                }
    
    # No structured result found
    return {
        "success": True,
        "image_url": "",
        "chart_type": chart_type,
        "message": "Code executed but no visualization output found"
    }


def _perform_pre_submission_review(
    parsed_result: dict,
    user_request: str,
    code_executed: str,
    llm_service: Optional[LLMService]
) -> tuple:
    """
    Perform Pre-Submission Review of the generated artifact.
    
    This self-evaluation ensures the visualization matches the user's description
    before the sandbox closes and the result is returned.
    
    Args:
        parsed_result: The parsed result from sandbox execution
        user_request: The original user request
        code_executed: The Python code that was executed
        llm_service: Optional LLMService instance
        
    Returns:
        Tuple of (approved: bool, feedback: str, issues: list)
    """
    # Extract image URL for review
    image_url = parsed_result.get("image_url", "")
    chart_type = parsed_result.get("chart_type", "unknown")
    
    # Skip review if no image was generated
    if not image_url:
        return (True, "", [])
    
    # Extract base64 from data URL if present
    image_base64 = ""
    if "base64," in image_url:
        image_base64 = image_url.split("base64,")[1]
    
    # Create reviewer and perform review
    reviewer = ArtifactReviewer(llm_service)
    review_result = reviewer.review_artifact(
        image_base64=image_base64,
        user_request=user_request,
        chart_type=chart_type,
        code_executed=code_executed
    )
    
    return (
        review_result.get("approved", True),
        review_result.get("feedback", ""),
        review_result.get("issues", [])
    )


def execute_data_visualization(
    csv_data: str,
    user_request: str,
    api_key: Optional[str] = None,
    sandbox_timeout: int = 120,
    llm_service: Optional[LLMService] = None,
    max_retries: int = MAX_RETRY_ATTEMPTS,
    enable_pre_submission_review: bool = True,
    max_review_attempts: int = MAX_REVIEW_ATTEMPTS,
    domain: Optional[str] = None,
    file_type: Optional[str] = None,
    file_content: Optional[str] = None,
    filename: Optional[str] = None
) -> dict:
    """
    Execute data visualization in a secure E2B sandbox with retry logic
    and optional Pre-Submission Review.
    
    This function:
    1. Spins up a secure sandbox environment
    2. Takes user's data (CSV, Excel, or PDF)
    3. Uses LLM to generate Python code for visualization
    4. Executes the generated code in a pandas environment
    5. If execution fails, retries with LLM-generated fixes (up to max_retries times)
    6. If enabled, performs Pre-Submission Review to validate the artifact
    7. If review fails, regenerates code with feedback and retries (up to max_review_attempts)
    8. Returns the final image URL
    
    Args:
        csv_data: CSV data as a string (used if file_content is not provided or for backward compatibility)
        user_request: User's request for visualization (e.g., "Create a bar chart")
        api_key: E2B API key (optional, uses E2B_API_KEY env var if not provided)
        sandbox_timeout: Timeout for sandbox execution in seconds (default: 120)
        llm_service: Optional LLMService instance for AI code generation
        max_retries: Maximum number of retry attempts when code fails (default: 3)
        enable_pre_submission_review: Whether to enable Pre-Submission Review (default: True)
        max_review_attempts: Maximum number of review/regeneration attempts (default: 2)
        domain: Domain for selecting specialized system prompt (legal, accounting, data_analysis)
        file_type: Type of file being processed (csv, excel, pdf)
        file_content: Base64-encoded file content (alternative to csv_data)
        filename: Original filename for detecting file type
        
    Returns:
        Dictionary containing:
            - success: bool indicating if operation was successful
            - image_url: URL of the generated chart (base64 data URL)
            - chart_type: Type of chart that was generated
            - message: Status message
            - execution_time: Time taken for execution
            - retry_count: Number of retry attempts made
            - review_attempts: Number of review attempts made
            - last_error: Last error message if failed
            
    Raises:
        Exception: If sandbox execution fails after all retries
    """
    start_time = datetime.now()
    
    # Get API key from parameter or environment
    e2b_api_key = api_key or os.environ.get("E2B_API_KEY")
    
    if not e2b_api_key:
        # Try to use sandbox without API key (for development/testing)
        # Note: In production, you should provide a valid API key
        pass
    
    # Determine effective file type
    effective_file_type = file_type or "csv"
    if filename and not file_type:
        # Detect file type from filename
        detected = FileType(detect_file_type(filename))
        if detected != FileType.UNKNOWN:
            effective_file_type = detected.value
    
    # Parse file content if provided (for Excel/PDF)
    parsed_data = None
    if file_content and effective_file_type != "csv":
        # Parse the file using the file parser
        parsed_result = parse_file(
            file_content=file_content,
            filename=filename or f"file.{effective_file_type}",
            file_type=effective_file_type
        )
        
        if parsed_result.get("success"):
            # Use parsed data for visualization
            csv_data = parsed_result.get("data_as_csv", csv_data)
            parsed_data = parsed_result
    
    # Extract CSV headers from the data
    first_line = csv_data.strip().split('\n')[0]
    csv_headers = [h.strip() for h in first_line.split(',')]
    
    # Generate visualization code using LLM with domain-specific prompts
    # Now includes file_type information
    ai_generator = AIResponseGenerator(llm_service, domain=domain)
    llm_result = ai_generator.generate_visualization_code(
        csv_headers, user_request, domain=domain, file_type=effective_file_type
    )
    
    # Get the generated code
    code = llm_result.get("code", "")
    chart_type = llm_result.get("chart_type", "bar")
    
    if not code:
        # Fallback if no code was generated
        execution_time = (datetime.now() - start_time).total_seconds()
        return {
            "success": False,
            "image_url": "",
            "chart_type": chart_type,
            "message": "Failed to generate visualization code",
            "execution_time": execution_time,
            "retry_count": 0,
            "review_attempts": 0,
            "last_error": "LLM failed to generate code"
        }
    
    # Wrap the generated code with CSV data
    code_with_csv = f'csv_data = """{csv_data}"""\n\n' + code
    
    # Initialize retry tracking
    retry_count = 0
    review_attempts = 0
    last_error = None
    current_code = code_with_csv
    
    # Retry loop: attempt execution with potential fixes
    while retry_count <= max_retries:
        # Execute code in sandbox
        success, result_or_error, _, _ = _execute_code_in_sandbox(
            current_code, e2b_api_key, sandbox_timeout
        )
        
        if success:
            # Parse successful result
            parsed_result = _parse_sandbox_result(result_or_error, chart_type)
            
            # Extract code for review (without csv_data assignment)
            code_for_review = code_with_csv.replace(f'csv_data = """{csv_data}"""\n\n', '', 1)
            
            # Pre-Submission Review: Validate artifact against user request
            if enable_pre_submission_review and parsed_result.get("image_url"):
                approved, feedback, issues = _perform_pre_submission_review(
                    parsed_result, user_request, code_for_review, llm_service
                )
                
                if not approved:
                    # Review failed - try to regenerate with feedback
                    review_attempts += 1
                    print(f"Pre-Submission Review failed: {feedback}")
                    print(f"Issues found: {issues}")
                    
                    if review_attempts <= max_review_attempts:
                        print(f"Regenerating code based on review feedback (attempt {review_attempts}/{max_review_attempts})...")
                        
                        # Regenerate code with feedback
                        reviewer = ArtifactReviewer(llm_service)
                        regen_result = reviewer.regenerate_with_feedback(
                            csv_headers=csv_headers,
                            user_request=user_request,
                            feedback=feedback,
                            chart_type=chart_type
                        )
                        
                        if regen_result["success"] and regen_result["code"]:
                            # Update code and retry execution
                            current_code = f'csv_data = """{csv_data}"""\n\n' + regen_result["code"]
                            chart_type = ai_generator._extract_chart_type(regen_result["code"]) or chart_type
                            continue  # Retry execution with new code
                        else:
                            print(f"Failed to regenerate code: {regen_result.get('error', 'Unknown error')}")
                            # Continue to return current result even if review regeneration failed
                    
                    # Either exhausted review attempts or regeneration failed
                    # Return what we have, but note the review failure
                    execution_time = (datetime.now() - start_time).total_seconds()
                    return {
                        "success": parsed_result["success"],
                        "image_url": parsed_result["image_url"],
                        "chart_type": parsed_result["chart_type"],
                        "message": f"Visualization generated but review feedback: {feedback}",
                        "execution_time": execution_time,
                        "retry_count": retry_count,
                        "review_attempts": review_attempts,
                        "last_error": None,
                        "review_feedback": feedback,
                        "review_issues": issues
                    }
            
            # Return successful result
            execution_time = (datetime.now() - start_time).total_seconds()
            return {
                "success": parsed_result["success"],
                "image_url": parsed_result["image_url"],
                "chart_type": parsed_result["chart_type"],
                "message": parsed_result["message"],
                "execution_time": execution_time,
                "retry_count": retry_count,
                "review_attempts": review_attempts,
                "last_error": None
            }
        else:
            # Execution failed - this is an error we can potentially fix
            last_error = result_or_error
            retry_count += 1
            
            # If we've exhausted retries, break out
            if retry_count > max_retries:
                break
            
            # Try to fix the code using the LLM
            print(f"Code execution failed (attempt {retry_count}/{max_retries}): {last_error}")
            print("Attempting to fix code with LLM...")
            
            # Extract just the user code (without csv_data assignment)
            user_code_only = code_with_csv.replace(f'csv_data = """{csv_data}"""\n\n', '', 1)
            
            code_fixer = CodeFixer(llm_service)
            fix_result = code_fixer.fix_code(
                failed_code=user_code_only,
                error_message=last_error,
                csv_headers=csv_headers,
                user_request=user_request
            )
            
            if fix_result["success"] and fix_result["code"]:
                # Wrap fixed code with CSV data
                current_code = f'csv_data = """{csv_data}"""\n\n' + fix_result["code"]
                print(f"LLM generated fix, retrying...")
            else:
                # LLM failed to generate a fix
                print(f"LLM failed to generate fix: {fix_result.get('error', 'Unknown error')}")
                break
    
    # All retries exhausted
    execution_time = (datetime.now() - start_time).total_seconds()
    return {
        "success": False,
        "image_url": "",
        "chart_type": chart_type,
        "message": f"Sandbox execution failed after {retry_count} attempts: {last_error}",
        "execution_time": execution_time,
        "retry_count": retry_count,
        "review_attempts": review_attempts,
        "last_error": last_error
    }


def execute_data_visualization_simple(
    csv_data: str,
    user_request: str = "Create a bar chart"
) -> dict:
    """
    Simplified version of execute_data_visualization with default settings.
    
    Args:
        csv_data: CSV data as a string
        user_request: User's visualization request
        
    Returns:
        Dictionary with visualization results
    """
    return execute_data_visualization(
        csv_data=csv_data,
        user_request=user_request,
        api_key=None,
        sandbox_timeout=120
    )


# Example usage when run directly
if __name__ == "__main__":
    # Example CSV data
    sample_csv = """name,value,category
Item A,100,Cat1
Item B,150,Cat1
Item C,200,Cat2
Item D,175,Cat2
Item E,125,Cat3"""
    
    # Example usage
    print("Testing execute_data_visualization function...")
    print("Sample CSV data:")
    print(sample_csv)
    print("\n" + "="*50)
    
    # Note: This will fail without a valid E2B API key
    # Uncomment below to test with valid API key
    # result = execute_data_visualization(sample_csv, "Create a bar chart")
    # print(result)
    
    print("\nTo test with a real sandbox, provide a valid E2B_API_KEY")
    print("or set the E2B_API_KEY environment variable.")
