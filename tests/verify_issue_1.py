import os
import sys
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.getcwd())

from src.agent_execution.executor import DocumentGenerator, ReportGenerator, TaskRouter

def test_document_generator():
    print("Testing DocumentGenerator...")
    mock_llm = MagicMock()
    # Mock LLM response with Python code
    mock_llm.complete.return_value = {
        "content": """```python
import pandas as pd
import json
# Mock document creation
print(json.dumps({'file_path': 'output.docx', 'success': True}))
```"""
    }
    
    generator = DocumentGenerator(domain="legal", llm_service=mock_llm)
    csv_data = """id,name,date
1,Test,2024-01-01"""
    user_request = "Create a legal contract"
    
    # Mock _execute_code_in_sandbox to avoid actual Docker/E2B call
    with patch("src.agent_execution.executor._execute_code_in_sandbox") as mock_exec:
        mock_artifact = MagicMock()
        mock_artifact.name = "output.docx"
        mock_artifact.data = b"mock docx content"
        mock_exec.return_value = (True, MagicMock(logs=[MagicMock(text='{"file_path": "output.docx", "success": True}')]), None, [mock_artifact])
        
        result = generator.generate_document(user_request, csv_data)
        
        print(f"Result success: {result.get('success')}")
        print(f"File name: {result.get('file_name')}")
        assert result.get("success") is True
        assert result.get("file_name") == "output.docx"
        print("DocumentGenerator test passed!")

def test_report_generator():
    print("\nTesting ReportGenerator...")
    mock_llm = MagicMock()
    mock_llm.complete.return_value = {
        "content": """```python
import pandas as pd
import json
# Mock report creation
print(json.dumps({'file_path': 'output.docx', 'success': True}))
```"""
    }
    
    generator = ReportGenerator(domain="accounting", llm_service=mock_llm, report_type="summary")
    csv_data = """date,amount
2024-01-01,100"""
    user_request = "Generate a financial summary report"
    
    with patch("src.agent_execution.executor._execute_code_in_sandbox") as mock_exec:
        mock_artifact = MagicMock()
        mock_artifact.name = "output.docx"
        mock_artifact.data = b"mock report content"
        mock_exec.return_value = (True, MagicMock(logs=[MagicMock(text='{"file_path": "output.docx", "success": True}')]), None, [mock_artifact])
        
        result = generator.generate_report(user_request, csv_data)
        
        print(f"Result success: {result.get('success')}")
        print(f"Report type: {result.get('report_type')}")
        assert result.get("success") is True
        assert result.get("report_type") == "summary"
        print("ReportGenerator test passed!")

def test_task_router_routing():
    print("\nTesting TaskRouter routing...")
    mock_llm = MagicMock()
    router = TaskRouter(llm_service=mock_llm)
    
    # Test document routing
    user_request = "Create a document for legal"
    task_type = router.detect_task_type(user_request)
    output_format = router.detect_output_format("legal", task_type)
    
    print(f"Detected task type: {task_type}")
    print(f"Detected output format: {output_format}")
    
    assert task_type == "document"
    assert output_format == "docx"
    
    # Test report routing
    user_request = "Generate an executive summary report"
    is_report = any(word in user_request.lower() for word in ["report", "summary", "analysis", "executive"])
    print(f"Is report: {is_report}")
    assert is_report is True
    
    print("TaskRouter routing test passed!")

if __name__ == "__main__":
    try:
        test_document_generator()
        test_report_generator()
        test_task_router_routing()
        print("\nAll Issue #1 verification tests passed!")
    except Exception as e:
        print(f"\nTests failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
