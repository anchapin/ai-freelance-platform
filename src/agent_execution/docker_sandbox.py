"""
Local Docker Sandbox - Drop-in replacement for E2B Code Interpreter

This module provides functionality for executing Python code in secure,
ephemeral Docker containers. It serves as a cost-free alternative to E2B.

Features:
- Ephemeral containers: Each execution uses a fresh container
- Pre-built image: Libraries pre-installed (no pip install overhead)
- Timeout support: Configurable execution timeout
- Artifact support: Returns generated files (images, documents, etc.)
- Automatic cleanup: Containers are removed after execution

Usage:
    with LocalDockerSandbox() as sandbox:
        result = sandbox.run_code("print('Hello, World!')")
        print(result.logs)
"""

import os
import json
import tempfile
from typing import Optional, List
from dataclasses import dataclass

# Docker SDK
try:
    import docker
    from docker.errors import DockerException, NotFound
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False
    DockerException = Exception


# =============================================================================
# CONFIGURATION
# =============================================================================

# Default Docker image for sandbox (should match Dockerfile.sandbox)
DEFAULT_IMAGE = os.environ.get("DOCKER_SANDBOX_IMAGE", "ai-sandbox-base")

# Default timeout in seconds
DEFAULT_TIMEOUT = int(os.environ.get("DOCKER_SANDBOX_TIMEOUT", "120"))


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SandboxLog:
    """Represents a log entry from sandbox execution."""
    text: str
    stream: str = "stdout"  # stdout or stderr
    
    def __repr__(self):
        return f"SandboxLog(text={self.text[:50]}..., stream={self.stream})"


@dataclass
class SandboxArtifact:
    """Represents a file artifact generated during execution."""
    name: str
    data: bytes
    mime_type: str = "application/octet-stream"
    
    def __repr__(self):
        return f"SandboxArtifact(name={self.name}, size={len(self.data)} bytes)"


@dataclass
class SandboxResult:
    """Represents the result of sandbox execution."""
    logs: List[SandboxLog]
    artifacts: List[SandboxArtifact]
    error: Optional[str] = None
    timed_out: bool = False
    
    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.error is None and not self.timed_out
    
    def __repr__(self):
        return f"SandboxResult(success={self.success}, logs={len(self.logs)}, artifacts={len(self.artifacts)})"


# =============================================================================
# LOCAL DOCKER SANDBOX CLASS
# =============================================================================

class LocalDockerSandbox:
    """
    A secure sandbox environment for executing Python code using Docker.
    
    This class provides a drop-in replacement for E2B's Code Interpreter,
    using local Docker containers instead of cloud-based execution.
    
    Features:
    - Ephemeral containers for isolation and security
    - Pre-built images to avoid pip install overhead
    - Configurable timeout
    - Artifact extraction (files created during execution)
    - Automatic cleanup
    
    Example:
        with LocalDockerSandbox() as sandbox:
            result = sandbox.run_code("print('Hello!')")
            print(result.logs)
    """
    
    def __init__(
        self,
        image: str = DEFAULT_IMAGE,
        timeout: int = DEFAULT_TIMEOUT,
        network_disabled: bool = True,
        memory_limit: str = "1g",
    ):
        """
        Initialize the Local Docker Sandbox.
        
        Args:
            image: Docker image to use for execution
            timeout: Maximum execution time in seconds
            network_disabled: Whether to disable network access in container
            memory_limit: Memory limit (e.g., "512m", "1g")
        """
        self.image = image
        self.timeout = timeout
        self.network_disabled = network_disabled
        self.memory_limit = memory_limit
        
        self._client = None
    
    def _get_docker_client(self) -> 'docker.DockerClient':
        """Get or create Docker client."""
        if not DOCKER_AVAILABLE:
            raise ImportError(
                "Docker SDK not available. Install with: pip install docker"
            )
        
        if self._client is None:
            try:
                # Try to connect to Docker daemon
                self._client = docker.from_env()
                # Verify connection
                self._client.ping()
            except DockerException as e:
                raise RuntimeError(
                    f"Failed to connect to Docker daemon: {e}. "
                    "Make sure Docker is running and accessible."
                )
        
        return self._client
    
    def _ensure_image_exists(self) -> bool:
        """
        Ensure the sandbox image exists locally.
        
        Returns:
            True if image is available
        """
        client = self._get_docker_client()
        
        try:
            client.images.get(self.image)
            return True
        except NotFound:
            print(f"Image '{self.image}' not found locally.")
            return False
        except Exception as e:
            print(f"Warning: Error checking for image: {e}")
            return False
    
    def _extract_artifacts(self, host_dir: str) -> List[SandboxArtifact]:
        """
        Extract artifacts from the host directory.
        
        Args:
            host_dir: Host directory where artifacts were written
            
        Returns:
            List of SandboxArtifact objects
        """
        artifacts = []
        
        # Known output files to look for
        output_files = [
            "output.png", "chart.png", "visualization.png", "figure.png",
            "output.docx", "document.docx", "report.docx",
            "output.pdf", "document.pdf", "report.pdf",
            "output.xlsx", "spreadsheet.xlsx", "data.xlsx"
        ]
        
        # MIME types mapping
        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".pdf": "application/pdf",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        }
        
        try:
            for filename in os.listdir(host_dir):
                if filename in output_files:
                    filepath = os.path.join(host_dir, filename)
                    try:
                        with open(filepath, 'rb') as f:
                            data = f.read()
                        
                        # Determine MIME type
                        ext = os.path.splitext(filename)[1].lower()
                        mime_type = mime_types.get(ext, "application/octet-stream")
                        
                        artifacts.append(SandboxArtifact(
                            name=filename,
                            data=data,
                            mime_type=mime_type
                        ))
                    except Exception:
                        pass  # Skip files that can't be read
        except Exception:
            pass  # Silently ignore extraction errors
        
        return artifacts
    
    def run_code(
        self,
        code: str,
        timeout: Optional[int] = None,
        output_format: str = "image"
    ) -> SandboxResult:
        """
        Execute Python code in the sandbox.
        
        Args:
            code: Python code to execute
            timeout: Override default timeout (in seconds)
            output_format: Expected output format for artifact extraction
            
        Returns:
            SandboxResult object containing logs and artifacts
        """
        effective_timeout = timeout or self.timeout
        
        # Ensure image exists
        if not self._ensure_image_exists():
            return SandboxResult(
                logs=[],
                artifacts=[],
                error=f"Docker image '{self.image}' not available"
            )
        
        client = self._get_docker_client()
        
        # Use context manager for automatic cleanup
        with tempfile.TemporaryDirectory() as host_dir:
            # Write Python script to host directory
            script_path = os.path.join(host_dir, "script.py")
            with open(script_path, 'w') as f:
                f.write(code)
            
            # Run container with the script
            try:
                container = client.containers.run(
                    self.image,
                    command="python script.py",
                    volumes={host_dir: {'bind': '/workspace', 'mode': 'rw'}},
                    working_dir="/workspace",
                    network_mode="none" if self.network_disabled else "bridge",
                    mem_limit=self.memory_limit,
                    detach=True,
                    remove=False  # We'll handle removal ourselves
                )
                
                # Wait for container with timeout
                try:
                    result = container.wait(timeout=effective_timeout)
                    exit_code = result.get("StatusCode", 0)
                except Exception as e:
                    # Check if it's a timeout
                    if "timeout" in str(e).lower():
                        container.stop(timeout=5)
                        container.remove(force=True)
                        return SandboxResult(
                            logs=[],
                            artifacts=[],
                            error=f"Execution timed out after {effective_timeout} seconds",
                            timed_out=True
                        )
                    raise
                
                # Get logs
                logs_output = container.logs().decode('utf-8', errors='replace')
                
                # Parse logs
                logs = []
                for line in logs_output.split('\n'):
                    if line.strip():
                        # Determine stream based on content
                        stream = "stderr" if any(x in line for x in ["Error", "Exception", "Traceback"]) else "stdout"
                        logs.append(SandboxLog(text=line + '\n', stream=stream))
                
                # Extract artifacts from mounted directory
                artifacts = self._extract_artifacts(host_dir)
                
                # Cleanup container
                try:
                    container.remove(force=True)
                except Exception:
                    pass
                
                # Check for errors
                error = None
                if exit_code != 0:
                    error = f"Process exited with code {exit_code}"
                
                return SandboxResult(
                    logs=logs,
                    artifacts=artifacts,
                    error=error,
                    timed_out=False
                )
                
            except DockerException as e:
                return SandboxResult(
                    logs=[],
                    artifacts=[],
                    error=f"Docker error: {str(e)}"
                )
            except Exception as e:
                return SandboxResult(
                    logs=[],
                    artifacts=[],
                    error=f"Execution error: {str(e)}"
                )
    
    # =========================================================================
    # CONTEXT MANAGER SUPPORT
    # =========================================================================
    
    def __enter__(self):
        """Enter context manager."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        # Cleanup handled by context manager for temp directory
        return False
    
    # =========================================================================
    # STATIC CONVENIENCE METHOD
    # =========================================================================
    
    @staticmethod
    def execute(
        code: str,
        image: str = DEFAULT_IMAGE,
        timeout: int = DEFAULT_TIMEOUT,
        output_format: str = "image"
    ) -> SandboxResult:
        """
        Execute code in a temporary sandbox (convenience method).
        
        This is a static method that creates a sandbox, executes code,
        and cleans up - all in one call.
        
        Args:
            code: Python code to execute
            image: Docker image to use
            timeout: Maximum execution time in seconds
            output_format: Expected output format
            
        Returns:
            SandboxResult object
        """
        with LocalDockerSandbox(image=image, timeout=timeout) as sandbox:
            return sandbox.run_code(code, output_format=output_format)


# =============================================================================
# HELPER FUNCTIONS (E2B COMPATIBLE INTERFACE)
# =============================================================================

def create_sandbox(
    api_key: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs
) -> LocalDockerSandbox:
    """
    Create a LocalDockerSandbox instance (E2B-compatible interface).
    
    Args:
        api_key: Ignored (kept for E2B compatibility)
        timeout: Maximum execution time
        **kwargs: Additional arguments
        
    Returns:
        LocalDockerSandbox instance
    """
    return LocalDockerSandbox(timeout=timeout, **kwargs)


def run_code_in_sandbox(
    code: str,
    sandbox: Optional[LocalDockerSandbox] = None,
    timeout: int = DEFAULT_TIMEOUT,
    output_format: str = "image"
) -> SandboxResult:
    """
    Execute code in sandbox (E2B-compatible interface).
    
    Args:
        code: Python code to execute
        sandbox: Existing sandbox instance (creates new if None)
        timeout: Maximum execution time
        output_format: Expected output format
        
    Returns:
        SandboxResult object
    """
    if sandbox is None:
        with LocalDockerSandbox(timeout=timeout) as s:
            return s.run_code(code, output_format=output_format)
    else:
        return sandbox.run_code(code, timeout=timeout, output_format=output_format)


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Example usage
    print("Testing Local Docker Sandbox...")
    
    # Simple test
    test_code = """
import pandas as pd
import matplotlib.pyplot as plt
import io
import base64
import json

# Create sample data
data = {'name': ['A', 'B', 'C'], 'value': [10, 20, 30]}
df = pd.DataFrame(data)

# Create a simple chart
fig, ax = plt.subplots()
df.plot(kind='bar', x='name', y='value', ax=ax)
ax.set_title('Test Chart')

# Save to buffer
buf = io.BytesIO()
plt.savefig(buf, format='png', dpi=100)
buf.seek(0)

# Encode to base64
img_base64 = base64.b64encode(buf.read()).decode('utf-8')

# Print result
result = {
    'image_url': f'data:image/png;base64,{img_base64}',
    'chart_type': 'bar',
    'columns': list(df.columns),
    'success': True
}
print(json.dumps(result))

plt.close()
"""
    
    try:
        # Try to execute
        result = LocalDockerSandbox.execute(test_code)
        
        print(f"Success: {result.success}")
        print(f"Logs: {len(result.logs)}")
        print(f"Artifacts: {len(result.artifacts)}")
        
        if result.error:
            print(f"Error: {result.error}")
        
    except Exception as e:
        print(f"Execution failed: {e}")
        print("Make sure Docker is running and the image is built.")
