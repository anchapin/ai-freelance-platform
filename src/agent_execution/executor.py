"""
E2B Code Interpreter Executor

This module provides functionality for executing code in secure sandboxes
using the E2B Code Interpreter SDK. It takes user's CSV data and generates
pandas data visualization charts inside a secure sandbox environment.

Features:
- Retry loop: If code fails (SyntaxError, runtime error, etc.), the LLM is asked to fix it
- Up to 3 retry attempts before giving up
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

# For type hints
try:
    from pandas import DataFrame
except ImportError:
    DataFrame = None  # Will be available in sandbox


# Maximum number of retry attempts when code fails
MAX_RETRY_ATTEMPTS = 3


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
    """
    
    def __init__(self, llm_service: Optional[LLMService] = None):
        """
        Initialize the AI response generator.
        
        Args:
            llm_service: Optional LLMService instance. If not provided,
                        creates one with default settings.
        """
        self.llm = llm_service or LLMService()
    
    def generate_visualization_code(
        self,
        csv_headers: list,
        user_request: str
    ) -> dict:
        """
        Generate Python code for data visualization using LLM.
        
        Args:
            csv_headers: List of CSV column headers
            user_request: The user's visualization request
            
        Returns:
            Dictionary containing:
                - code: Python code to execute
                - chart_type: Type of chart being generated
                - description: Description of what the code does
        """
        # Robust system prompt that explicitly instructs the LLM
        system_prompt = """You are an expert data scientist. The user wants to visualize data from a CSV file.

I will provide you with:
1. The CSV column headers
2. The user's visualization request

Your task is to generate ONLY valid Python code (not JSON) that:
- Uses pandas to read CSV data from a variable named 'csv_data' (a string)
- Uses matplotlib to create an appropriate visualization
- Saves the figure to a base64-encoded PNG string in a variable named 'img_base64'
- Prints a JSON result with these exact keys: image_url, chart_type, columns, success

The code MUST:
1. Read CSV using: df = pd.read_csv(io.StringIO(csv_data))
2. Create appropriate matplotlib chart based on user's request
3. Save to base64: img_base64 = base64.b64encode(buf.read()).decode('utf-8')
4. Print: print(json.dumps({'image_url': f'data:image/png;base64,{img_base64}', 'chart_type': '...', 'columns': [...], 'success': True}}))

Return ONLY the Python code, no explanations or markdown. The code should be complete and ready to execute."""

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


def execute_data_visualization(
    csv_data: str,
    user_request: str,
    api_key: Optional[str] = None,
    sandbox_timeout: int = 120,
    llm_service: Optional[LLMService] = None,
    max_retries: int = MAX_RETRY_ATTEMPTS
) -> dict:
    """
    Execute data visualization in a secure E2B sandbox with retry logic.
    
    This function:
    1. Spins up a secure sandbox environment
    2. Takes user's CSV data
    3. Uses LLM to generate Python code for visualization
    4. Executes the generated code in a pandas environment
    5. If execution fails, retries with LLM-generated fixes (up to max_retries times)
    6. Returns the final image URL
    
    Args:
        csv_data: CSV data as a string
        user_request: User's request for visualization (e.g., "Create a bar chart")
        api_key: E2B API key (optional, uses E2B_API_KEY env var if not provided)
        sandbox_timeout: Timeout for sandbox execution in seconds (default: 120)
        llm_service: Optional LLMService instance for AI code generation
        max_retries: Maximum number of retry attempts when code fails (default: 3)
        
    Returns:
        Dictionary containing:
            - success: bool indicating if operation was successful
            - image_url: URL of the generated chart (base64 data URL)
            - chart_type: Type of chart that was generated
            - message: Status message
            - execution_time: Time taken for execution
            - retry_count: Number of retry attempts made
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
    
    # Extract CSV headers from the data
    first_line = csv_data.strip().split('\n')[0]
    csv_headers = [h.strip() for h in first_line.split(',')]
    
    # Generate visualization code using LLM
    ai_generator = AIResponseGenerator(llm_service)
    llm_result = ai_generator.generate_visualization_code(csv_headers, user_request)
    
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
            "last_error": "LLM failed to generate code"
        }
    
    # Wrap the generated code with CSV data
    code_with_csv = f'csv_data = """{csv_data}"""\n\n' + code
    
    # Initialize retry tracking
    retry_count = 0
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
            execution_time = (datetime.now() - start_time).total_seconds()
            
            return {
                "success": parsed_result["success"],
                "image_url": parsed_result["image_url"],
                "chart_type": parsed_result["chart_type"],
                "message": parsed_result["message"],
                "execution_time": execution_time,
                "retry_count": retry_count,
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
