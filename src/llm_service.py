"""
LLM Service Module

This module provides an OpenAI client wrapper for interacting with Large Language Models.
It supports both cloud providers (OpenAI, Anthropic, etc.) and local inference via Ollama/llama.cpp.

Features:
- Task-type based model selection (e.g., use local models for "Basic Admin" tasks)
- Automatic fallback from cloud to local when cloud fails
- Configurable per-task model mappings
"""

from openai import OpenAI
from dotenv import load_dotenv
import os
import time
import random
from typing import Optional, Dict, Any, List

# Load environment variables from .env file
# Create a .env file in your project root with the following variables:
# BASE_URL=https://api.openai.com/v1
# API_KEY=your-api-key-here
load_dotenv()


# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

# Default model configurations
DEFAULT_CLOUD_MODEL = "gpt-4o-mini"
DEFAULT_LOCAL_MODEL = "llama3.2"  # Common Ollama model name
DEFAULT_DISTILLED_MODEL = "distilled-llama3.2"  # Fine-tuned distilled model

# Default task type classifications
TASK_TYPE_BASIC_ADMIN = "basic_admin"  # Simple tasks, suitable for local models
TASK_TYPE_COMPLEX = "complex"          # Complex tasks requiring powerful models
TASK_TYPE_DISTILLED = "distilled"     # Tasks handled by fine-tuned local model

# Revenue threshold for cloud vs local model selection (in cents)
# Default: $30 - below this use local, above this use cloud
MIN_CLOUD_REVENUE = int(os.environ.get("MIN_CLOUD_REVENUE", "3000"))


class ModelConfig:
    """
    Configuration for model selection based on task type.
    
    Allows specifying different models for different task types,
    with support for both cloud and local inference.
    """
    
    def __init__(
        self,
        cloud_model: str = DEFAULT_CLOUD_MODEL,
        local_model: str = DEFAULT_LOCAL_MODEL,
        local_base_url: str = "http://localhost:11434/v1",
        local_api_key: str = "not-needed",
        use_local_by_default: bool = False,
        task_model_map: Optional[Dict[str, str]] = None,
        task_use_local_map: Optional[Dict[str, bool]] = None
    ):
        """
        Initialize model configuration.
        
        Args:
            cloud_model: Default cloud model (e.g., "gpt-4o-mini")
            local_model: Default local model (e.g., "llama3.2")
            local_base_url: Base URL for local inference (e.g., "http://localhost:11434/v1")
            local_api_key: API key for local inference (usually not needed)
            use_local_by_default: Whether to use local models by default for all tasks
            task_model_map: Optional dict mapping task types to specific models
                           e.g., {"basic_admin": "llama3.2", "complex": "gpt-4o"}
            task_use_local_map: Optional dict mapping task types to local/cloud preference
                               e.g., {"basic_admin": True, "complex": False}
        """
        self.cloud_model = cloud_model
        self.local_model = local_model
        self.local_base_url = local_base_url
        self.local_api_key = local_api_key
        self.use_local_by_default = use_local_by_default
        self.task_model_map = task_model_map or {}
        self.task_use_local_map = task_use_local_map or {}
    
    @classmethod
    def from_env(cls) -> "ModelConfig":
        """
        Create ModelConfig from environment variables.
        
        Environment variables:
        - CLOUD_MODEL: Default cloud model
        - LOCAL_MODEL: Default local model  
        - LOCAL_BASE_URL: Base URL for local inference (default: http://localhost:11434/v1)
        - USE_LOCAL_BY_DEFAULT: Set to "true" to use local models by default
        - TASK_MODEL_MAP: JSON string mapping task types to models
        - TASK_USE_LOCAL_MAP: JSON string mapping task types to local preference
        
        Example .env:
            CLOUD_MODEL=gpt-4o-mini
            LOCAL_MODEL=llama3.2
            USE_LOCAL_BY_DEFAULT=false
            TASK_MODEL_MAP={"basic_admin":"llama3.2","complex":"gpt-4o"}
            TASK_USE_LOCAL_MAP={"basic_admin":true,"complex":false}
        """
        import json
        
        # Parse task model map from JSON string
        task_model_str = os.environ.get("TASK_MODEL_MAP", "{}")
        try:
            task_model_map = json.loads(task_model_str)
        except json.JSONDecodeError:
            task_model_map = {}
        
        # Parse task use local map from JSON string
        task_use_local_str = os.environ.get("TASK_USE_LOCAL_MAP", "{}")
        try:
            task_use_local_map = json.loads(task_use_local_str)
        except json.JSONDecodeError:
            task_use_local_map = {}
        
        return cls(
            cloud_model=os.environ.get("CLOUD_MODEL", DEFAULT_CLOUD_MODEL),
            local_model=os.environ.get("LOCAL_MODEL", DEFAULT_LOCAL_MODEL),
            local_base_url=os.environ.get("LOCAL_BASE_URL", "http://localhost:11434/v1"),
            local_api_key=os.environ.get("LOCAL_API_KEY", "not-needed"),
            use_local_by_default=os.environ.get("USE_LOCAL_BY_DEFAULT", "false").lower() == "true",
            task_model_map=task_model_map,
            task_use_local_map=task_use_local_map
        )
    
    def get_model_for_task(self, task_type: str, prefer_local: Optional[bool] = None) -> tuple:
        """
        Get the appropriate model and configuration for a task type.
        
        Args:
            task_type: The type of task (e.g., "basic_admin", "complex")
            prefer_local: Override the local preference for this specific call
            
        Returns:
            Tuple of (model_name, base_url, api_key, is_local)
        """
        # Determine if we should use local model
        use_local = prefer_local if prefer_local is not None else self.use_local_by_default
        
        # Check task-specific override
        if task_type in self.task_use_local_map:
            use_local = self.task_use_local_map[task_type]
        
        # Get the model name
        model = self.local_model if use_local else self.cloud_model
        
        # Check for task-specific model override
        if task_type in self.task_model_map:
            model = self.task_model_map[task_type]
        
        # Return configuration
        if use_local:
            return (model, self.local_base_url, self.local_api_key, True)
        else:
            return (model, os.environ.get("BASE_URL", "https://api.openai.com/v1"), 
                    os.environ.get("API_KEY", "dummy-key-for-local"), False)


# Global default model config
_default_model_config: Optional[ModelConfig] = None


def get_default_model_config() -> ModelConfig:
    """Get or create the default model configuration."""
    global _default_model_config
    if _default_model_config is None:
        _default_model_config = ModelConfig.from_env()
    return _default_model_config


def set_default_model_config(config: ModelConfig):
    """Set the default model configuration."""
    global _default_model_config
    _default_model_config = config


class LLMService:
    """
    A wrapper class for the OpenAI client that supports configurable base URLs.
    
    This allows switching between cloud providers (OpenAI, Anthropic, etc.) 
    and local inference engines (Ollama, llama.cpp, LM Studio, etc.).
    
    Features:
    - Task-type based model selection
    - Automatic fallback between cloud and local
    - Configurable model mappings per task type
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        default_temperature: float = 0.7,
        default_max_tokens: int = 1000,
        model_config: Optional[ModelConfig] = None,
        enable_fallback: bool = True
    ):
        """
        Initialize the LLM Service.
        
        Args:
            base_url: The base URL for the API endpoint.
                     If not provided, reads from BASE_URL environment variable or .env file.
                     
                     # =========================================================================
                     # CONFIGURING THE BASE URL
                     # =========================================================================
                     # 
                     # CLOUD PROVIDERS (use these URLs for commercial LLM APIs):
                     # 
                     # OpenAI:           https://api.openai.com/v1
                     # Anthropic:        https://api.anthropic.com (requires custom client)
                     # Google Gemini:     https://generativelanguage.googleapis.com/v1
                     # Cohere:           https://api.cohere.ai/v1
                     # Mistral:          https://api.mistral.ai/v1
                     #
                     # LOCAL INFERENCE (use this URL for local Ollama/llama.cpp):
                     # 
                     # Ollama:           http://localhost:11434/v1
                     # llama.cpp/LM Studio: http://localhost:1234/v1
                     # vLLM:             http://localhost:8000/v1
                     #
                     # Example for local Ollama:
                     #   base_url="http://localhost:11434/v1"
                     #   api_key="not-needed"  # Ollama doesn't require API keys
                     #
                     # =========================================================================
                     
            api_key: The API key for authentication.
                    If not provided, reads from API_KEY environment variable or .env file.
                    Note: Local inference servers like Ollama often don't require API keys.
            model: The default model to use for completions.
            default_temperature: Default temperature for generation.
            default_max_tokens: Default maximum tokens to generate.
            model_config: Optional ModelConfig for task-based model selection.
            enable_fallback: Whether to automatically try local if cloud fails.
        """
        # Get base_url from parameter, environment, or .env file
        self.base_url = base_url or os.environ.get("BASE_URL", "https://api.openai.com/v1")
        
        # Get api_key from parameter, environment, or .env file
        # For local Ollama/llama.cpp, you can set this to any placeholder value
        # or use "not-needed" / "ollama" as the API key
        self.api_key = api_key or os.environ.get("API_KEY", "dummy-key-for-local")
        
        self.model = model
        self.default_temperature = default_temperature
        self.default_max_tokens = default_max_tokens
        self.model_config = model_config or get_default_model_config()
        self.enable_fallback = enable_fallback
        
        # Track if we're currently using local
        self._is_local = "localhost" in self.base_url or "127.0.0.1" in self.base_url
        
        # Initialize the OpenAI client with custom base URL
        self.client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key
        )
    
    def complete(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        stealth_mode: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a completion from the LLM.
        
        Args:
            prompt: The user prompt/input
            temperature: Sampling temperature (0.0 to 2.0). Higher = more creative
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt to set context
            stealth_mode: If True, adds random delay (2-5 seconds) to mimic human typing
            **kwargs: Additional parameters passed to the API
            
        Returns:
            Dictionary containing the response text and metadata
        """
        # Stealth mode: add random delay to mimic human typing speed
        if stealth_mode:
            delay = random.uniform(2.0, 5.0)
            time.sleep(delay)
        
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature or self.default_temperature,
            max_tokens=max_tokens or self.default_max_tokens,
            **kwargs
        )
        
        return {
            "content": response.choices[0].message.content,
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            },
            "stealth_mode_used": stealth_mode
        }
    
    def complete_streaming(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        **kwargs
    ):
        """
        Generate a streaming completion from the LLM.
        
        Args:
            prompt: The user prompt/input
            temperature: Sampling temperature (0.0 to 2.0)
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt
            **kwargs: Additional parameters
            
        Yields:
            Chunks of the response text
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature or self.default_temperature,
            max_tokens=max_tokens or self.default_max_tokens,
            stream=True,
            **kwargs
        )
        
        for chunk in response:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    def set_model(self, model: str):
        """Update the default model."""
        self.model = model
    
    def get_model(self) -> str:
        """Get the current model name."""
        return self.model
    
    def get_config(self) -> Dict[str, str]:
        """Get current configuration (excluding sensitive API key)."""
        return {
            "base_url": self.base_url,
            "model": self.model,
            "temperature": self.default_temperature,
            "max_tokens": self.default_max_tokens,
            "is_local": self._is_local,
            "enable_fallback": self.enable_fallback
        }
    
    def is_local(self) -> bool:
        """Check if currently using local inference."""
        return self._is_local
    
    # =========================================================================
    # TASK-BASED FACTORY METHODS
    # =========================================================================
    
    @classmethod
    def for_task(
        cls,
        task_type: str,
        model_config: Optional[ModelConfig] = None,
        **kwargs
    ) -> "LLMService":
        """
        Create an LLMService instance configured for a specific task type.
        
        Args:
            task_type: The type of task (e.g., "basic_admin", "complex")
            model_config: Optional ModelConfig, uses default if not provided
            **kwargs: Additional arguments passed to LLMService constructor
            
        Returns:
            Configured LLMService instance
        """
        config = model_config or get_default_model_config()
        model, base_url, api_key, is_local = config.get_model_for_task(task_type)
        
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            model_config=config,
            **kwargs
        )
    
    @classmethod
    def for_basic_admin(cls, **kwargs) -> "LLMService":
        """
        Create an LLMService for "Basic Admin" tasks using local model.
        
        This is suitable for simple tasks that don't require powerful models,
        allowing cost savings by using local inference.
        
        Args:
            **kwargs: Additional arguments passed to LLMService constructor
            
        Returns:
            LLMService configured for basic admin tasks
        """
        return cls.for_task(TASK_TYPE_BASIC_ADMIN, **kwargs)
    
    @classmethod
    def for_complex_task(cls, **kwargs) -> "LLMService":
        """
        Create an LLMService for complex tasks using cloud model.
        
        This is suitable for complex tasks that require powerful models,
        using cloud inference for best results.
        
        Args:
            **kwargs: Additional arguments passed to LLMService constructor
            
        Returns:
            LLMService configured for complex tasks
        """
        return cls.for_task(TASK_TYPE_COMPLEX, **kwargs)
    
    @classmethod
    def for_distilled_task(cls, model: Optional[str] = None, **kwargs) -> "LLMService":
        """
        Create an LLMService for distilled tasks using fine-tuned local model.
        
        This uses your fine-tuned local model that was trained on successful
        outputs from GPT-4o. This gives you cloud-quality results at local costs!
        
        The model should be configured via TASK_MODEL_MAP or DISTILLED_MODEL_NAME env vars.
        
        Args:
            model: Optional override for the distilled model name
            **kwargs: Additional arguments passed to LLMService constructor
            
        Returns:
            LLMService configured for distilled tasks (fine-tuned local model)
        """
        config = get_default_model_config()
        
        # Get the distilled model name from config or environment
        distilled_model = model or os.environ.get("DISTILLED_MODEL_NAME", DEFAULT_DISTILLED_MODEL)
        
        return cls(
            base_url=config.local_base_url,  # Distilled model runs locally via Ollama
            api_key=config.local_api_key,
            model=distilled_model,
            model_config=config,
            **kwargs
        )
    
    @classmethod
    def with_local(cls, model: Optional[str] = None, **kwargs) -> "LLMService":
        """
        Create an LLMService configured for local inference.
        
        Args:
            model: Optional model name (defaults to config's local_model)
            **kwargs: Additional arguments passed to LLMService constructor
            
        Returns:
            LLMService configured for local inference
        """
        config = get_default_model_config()
        return cls(
            base_url=config.local_base_url,
            api_key=config.local_api_key,
            model=model or config.local_model,
            model_config=config,
            **kwargs
        )
    
    @classmethod
    def with_cloud(cls, model: Optional[str] = None, **kwargs) -> "LLMService":
        """
        Create an LLMService configured for cloud inference.
        
        Args:
            model: Optional model name (defaults to config's cloud_model)
            **kwargs: Additional arguments passed to LLMService constructor
            
        Returns:
            LLMService configured for cloud inference
        """
        config = get_default_model_config()
        return cls(
            base_url=os.environ.get("BASE_URL", "https://api.openai.com/v1"),
            api_key=os.environ.get("API_KEY", "dummy-key-for-local"),
            model=model or config.cloud_model,
            model_config=config,
            **kwargs
        )
    
    # =========================================================================
    # REVENUE-BASED OPTIMIZATION
    # =========================================================================
    
    @classmethod
    def get_optimized_service(
        cls,
        potential_revenue_cents: int,
        min_cloud_revenue: Optional[int] = None,
        **kwargs
    ) -> "LLMService":
        """
        Get an optimized LLMService based on potential revenue.
        
        Uses revenue-based model selection to optimize costs:
        - Below MIN_CLOUD_REVENUE threshold: Use local model (free)
        - Above threshold: Use cloud model (best quality)
        
        Args:
            potential_revenue_cents: The potential revenue in cents (e.g., 2500 = $25)
            min_cloud_revenue: Optional override for MIN_CLOUD_REVENUE threshold (in cents)
                             Defaults to $30 (3000 cents) if not specified
            **kwargs: Additional arguments passed to LLMService constructor
            
        Returns:
            LLMService configured for optimal model based on revenue
        """
        threshold = min_cloud_revenue if min_cloud_revenue is not None else MIN_CLOUD_REVENUE
        
        if potential_revenue_cents < threshold:
            # Low revenue: use local model (free, cost optimization)
            return cls.with_local(**kwargs)
        else:
            # High revenue: use cloud model (best quality for high-value tasks)
            return cls.with_cloud(**kwargs)
    
    # =========================================================================
    # FALLBACK MECHANISM
    # =========================================================================
    
    def complete_with_fallback(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a completion with automatic fallback to local model if cloud fails.
        
        This method attempts the request with the current configuration,
        and if it fails and fallback is enabled, tries the local model.
        
        Args:
            prompt: The user prompt/input
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing the response text and metadata
        """
        # Try current configuration first
        try:
            return self.complete(
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                **kwargs
            )
        except Exception as cloud_error:
            # If cloud failed and fallback is enabled, try local
            if self.enable_fallback and not self._is_local:
                print(f"Cloud inference failed: {cloud_error}")
                print("Attempting fallback to local model...")
                
                # Create local service
                local_service = self.with_local()
                
                try:
                    result = local_service.complete(
                        prompt=prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        system_prompt=system_prompt,
                        **kwargs
                    )
                    # Add fallback info to result
                    result["fallback_used"] = True
                    result["original_error"] = str(cloud_error)
                    return result
                except Exception as local_error:
                    # Both failed, raise the original cloud error
                    raise cloud_error
            
            # Fallback disabled or already local, re-raise
            raise


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

if __name__ == "__main__":
    # Example 1: Using cloud provider (OpenAI)
    # Create a .env file with:
    # BASE_URL=https://api.openai.com/v1
    # API_KEY=your-openai-api-key
    
    print("=" * 60)
    print("LLM Service - Usage Examples")
    print("=" * 60)
    
    # Example 2: Using local Ollama
    # For local Ollama, create a .env file with:
    # BASE_URL=http://localhost:11434/v1
    # API_KEY=not-needed
    
    # Initialize with local Ollama
    llm = LLMService(
        base_url="http://localhost:11434/v1",
        api_key="not-needed",
        model="llama3.2"  # or whatever model you have installed in Ollama
    )
    
    print("\nConfiguration:")
    print(llm.get_config())
    
    print("\n" + "-" * 60)
    print("To test the service:")
    print("1. For cloud: Set BASE_URL and API_KEY in .env file")
    print("2. For local: Run 'ollama serve' and ensure model is installed")
    print("3. Uncomment the completion call below to test")
    print("-" * 60)
    
    # Test the service (uncomment to test)
    # try:
    #     result = llm.complete("What is the capital of France?")
    #     print(f"\nResponse: {result['content']}")
    # except Exception as e:
    #     print(f"\nError (make sure Ollama is running): {e}")
    
    print("\nStreaming example:")
    print("-" * 60)
    print("""
# For streaming responses:
for chunk in llm.complete_streaming("Count to 5"):
    print(chunk, end="", flush=True)
print()  # Newline after streaming
""")
