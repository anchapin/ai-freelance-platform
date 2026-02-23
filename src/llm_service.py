"""
LLM Service Module

This module provides an OpenAI client wrapper for interacting with Large Language Models.
It supports both cloud providers (OpenAI, Anthropic, etc.) and local inference via Ollama/llama.cpp.
"""

from openai import OpenAI
from dotenv import load_dotenv
import os
from typing import Optional, Dict, Any

# Load environment variables from .env file
# Create a .env file in your project root with the following variables:
# BASE_URL=https://api.openai.com/v1
# API_KEY=your-api-key-here
load_dotenv()


class LLMService:
    """
    A wrapper class for the OpenAI client that supports configurable base URLs.
    
    This allows switching between cloud providers (OpenAI, Anthropic, etc.) 
    and local inference engines (Ollama, llama.cpp, LM Studio, etc.).
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        default_temperature: float = 0.7,
        default_max_tokens: int = 1000
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
        **kwargs
    ) -> Dict[str, Any]:
        """
        Generate a completion from the LLM.
        
        Args:
            prompt: The user prompt/input
            temperature: Sampling temperature (0.0 to 2.0). Higher = more creative
            max_tokens: Maximum tokens to generate
            system_prompt: Optional system prompt to set context
            **kwargs: Additional parameters passed to the API
            
        Returns:
            Dictionary containing the response text and metadata
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
            **kwargs
        )
        
        return {
            "content": response.choices[0].message.content,
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
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
            "max_tokens": self.default_max_tokens
        }


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
