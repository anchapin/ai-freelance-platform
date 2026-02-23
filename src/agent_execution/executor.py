"""
E2B Code Interpreter Executor

This module provides functionality for executing code in secure sandboxes
using the E2B Code Interpreter SDK. It takes user's CSV data and generates
pandas data visualization charts inside a secure sandbox environment.
"""

import os
import io
import base64
from typing import Optional
from datetime import datetime

# E2B Code Interpreter SDK
from e2b_code_interpreter import Sandbox

# For type hints
try:
    from pandas import DataFrame
except ImportError:
    DataFrame = None  # Will be available in sandbox


class MockAIResponse:
    """
    Mock AI response generator for demonstration purposes.
    In production, this would be replaced with actual AI/LLM integration.
    """
    
    @staticmethod
    def generate_visualization_config(csv_data: str, user_request: str) -> dict:
        """
        Generate visualization configuration based on user request and CSV data.
        
        Args:
            csv_data: The CSV data provided by the user
            user_request: The user's visualization request
            
        Returns:
            Dictionary containing visualization configuration
        """
        # Default visualization configuration
        # In production, this would use an LLM to generate the appropriate config
        config = {
            "chart_type": "bar",
            "title": "Data Visualization",
            "x_column": None,
            "y_column": None,
            "color": "#4F46E5",
        }
        
        # Simple heuristic to determine chart type based on request
        request_lower = user_request.lower()
        
        if "line" in request_lower:
            config["chart_type"] = "line"
        elif "pie" in request_lower:
            config["chart_type"] = "pie"
        elif "scatter" in request_lower:
            config["chart_type"] = "scatter"
        elif "histogram" in request_lower or "distribution" in request_lower:
            config["chart_type"] = "histogram"
        elif "bar" in request_lower:
            config["chart_type"] = "bar"
        else:
            config["chart_type"] = "bar"  # Default
            
        return config


def execute_data_visualization(
    csv_data: str,
    user_request: str,
    api_key: Optional[str] = None,
    sandbox_timeout: int = 120
) -> dict:
    """
    Execute data visualization in a secure E2B sandbox.
    
    This function:
    1. Spins up a secure sandbox environment
    2. Takes user's CSV data
    3. Uses mock AI to generate visualization config
    4. Creates a pandas data visualization chart
    5. Returns the final image URL
    
    Args:
        csv_data: CSV data as a string
        user_request: User's request for visualization (e.g., "Create a bar chart")
        api_key: E2B API key (optional, uses E2B_API_KEY env var if not provided)
        sandbox_timeout: Timeout for sandbox execution in seconds (default: 120)
        
    Returns:
        Dictionary containing:
            - success: bool indicating if operation was successful
            - image_url: URL of the generated chart (base64 data URL)
            - chart_type: Type of chart that was generated
            - message: Status message
            - execution_time: Time taken for execution
            
    Raises:
        Exception: If sandbox execution fails
    """
    start_time = datetime.now()
    
    # Get API key from parameter or environment
    e2b_api_key = api_key or os.environ.get("E2B_API_KEY")
    
    if not e2b_api_key:
        # Try to use sandbox without API key (for development/testing)
        # Note: In production, you should provide a valid API key
        pass
    
    # Generate visualization config using mock AI
    ai_config = MockAIResponse.generate_visualization_config(csv_data, user_request)
    
    # Code to execute in the sandbox
    code = f"""
import pandas as pd
import matplotlib.pyplot as plt
import base64
import io
import json

# Read CSV data from the provided string
csv_data = '''{csv_data}'''

# Parse CSV data into pandas DataFrame
df = pd.read_csv(io.StringIO(csv_data))

# Display basic info about the data
print("Data shape:", df.shape)
print("Columns:", df.columns.tolist())
print("First few rows:")
print(df.head())

# Visualization configuration from AI
config = {json.dumps(ai_config)}

# Set up the figure
fig, ax = plt.subplots(figsize=(10, 6))
fig.patch.set_facecolor('white')

chart_type = config.get('chart_type', 'bar')

# Get columns for visualization
columns = df.columns.tolist()
x_col = config.get('x_column') or (columns[0] if len(columns) > 0 else None)
y_col = config.get('y_column') or (columns[1] if len(columns) > 1 else columns[0])

# Generate the appropriate chart type
if chart_type == 'bar':
    if y_col and y_col in df.columns:
        df.plot(kind='bar', x=x_col, y=y_col, ax=ax, color=config.get('color', '#4F46E5'))
    else:
        df.plot(kind='bar', ax=ax, color=config.get('color', '#4F46E5'))
        
elif chart_type == 'line':
    if y_col and y_col in df.columns:
        df.plot(kind='line', x=x_col, y=y_col, ax=ax, color=config.get('color', '#4F46E5'))
    else:
        df.plot(kind='line', ax=ax, color=config.get('color', '#4F46E5'))
        
elif chart_type == 'scatter':
    if len(columns) >= 2:
        df.plot(kind='scatter', x=columns[0], y=columns[1], ax=ax, 
                c=config.get('color', '#4F46E5'), alpha=0.7)
        
elif chart_type == 'pie':
    if y_col and y_col in df.columns:
        df.plot(kind='pie', y=y_col, ax=ax, autopct='%1.1f%%', 
                colors=plt.cm.Set3.colors)
        
elif chart_type == 'histogram':
    if y_col and y_col in df.columns:
        df[y_col].plot(kind='hist', ax=ax, bins=20, 
                       color=config.get('color', '#4F46E5'), alpha=0.7)
    else:
        df.hist(ax=ax, bins=20, color=config.get('color', '#4F46E5'), alpha=0.7)

else:
    # Default to bar chart
    df.plot(kind='bar', ax=ax, color=config.get('color', '#4F46E5'))

# Customize the chart
ax.set_title(config.get('title', 'Data Visualization'), fontsize=14, fontweight='bold')
ax.set_xlabel(x_col if x_col else 'Index', fontsize=12)
ax.set_ylabel('Value', fontsize=12)
plt.xticks(rotation=45, ha='right')
plt.tight_layout()

# Save to bytes
buf = io.BytesIO()
plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', 
            facecolor='white', edgecolor='none')
buf.seek(0)

# Convert to base64
img_base64 = base64.b64encode(buf.read()).decode('utf-8')
plt.close(fig)

# Return the result as a data URL
result = {{
    'image_url': f'data:image/png;base64,{{img_base64}}',
    'chart_type': chart_type,
    'columns': columns,
    'success': True
}}

print("\\n" + "="*50)
print("Visualization generated successfully!")
print("="*50)
print(json.dumps(result))
"""
    
    # Execute in E2B sandbox
    try:
        with Sandbox(api_key=e2b_api_key) as sandbox:
            # Run the code in the sandbox
            result = sandbox.run_code(
                code,
                timeout=sandbox_timeout
            )
            
            # Parse the result
            if result.logs:
                # Find the JSON output in logs
                for log in result.logs:
                    if hasattr(log, 'text') and log.text:
                        try:
                            # Try to parse the JSON result from the output
                            if "{" in log.text and "}" in log.text:
                                json_start = log.text.find("{")
                                json_end = log.text.rfind("}") + 1
                                json_str = log.text[json_start:json_end]
                                result_data = eval(json_str)  # Safe here since we generated the code
                                
                                execution_time = (datetime.now() - start_time).total_seconds()
                                
                                return {
                                    "success": result_data.get("success", True),
                                    "image_url": result_data.get("image_url", ""),
                                    "chart_type": result_data.get("chart_type", ai_config["chart_type"]),
                                    "message": "Visualization generated successfully",
                                    "execution_time": execution_time
                                }
                        except (SyntaxError, ValueError):
                            continue
            
            # If no structured result found, try to get the image from artifacts
            if result.artifacts:
                for artifact in result.artifacts:
                    if hasattr(artifact, 'data'):
                        execution_time = (datetime.now() - start_time).total_seconds()
                        return {
                            "success": True,
                            "image_url": f"data:image/png;base64,{base64.b64encode(artifact.data).decode('utf-8')}",
                            "chart_type": ai_config["chart_type"],
                            "message": "Visualization generated from artifact",
                            "execution_time": execution_time
                        }
            
            # Fallback: generate a placeholder result
            execution_time = (datetime.now() - start_time).total_seconds()
            return {
                "success": True,
                "image_url": "",
                "chart_type": ai_config["chart_type"],
                "message": "Code executed but no visualization output found",
                "execution_time": execution_time
            }
            
    except Exception as e:
        execution_time = (datetime.now() - start_time).total_seconds()
        return {
            "success": False,
            "image_url": "",
            "chart_type": ai_config["chart_type"],
            "message": f"Sandbox execution failed: {str(e)}",
            "execution_time": execution_time
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
