"""
Experience Vector Database (RAG for Few-Shot Learning)

This module provides a vector database for storing and retrieving successful task experiences.
When a task is marked as COMPLETED and approved, the user_request and final successful code
are stored in ChromaDB. When a new task comes in, we query for the top 2 most similar past tasks
and inject those as examples in the LLM's system prompt to reduce hallucination and failure loops.

Features:
- ChromaDB for persistent vector storage
- Sentence-transformers for text embeddings
- Domain-aware similarity search
- Few-shot example generation for LLM prompts
"""

import os
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

# ChromaDB for vector storage
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("Warning: ChromaDB not available. Experience Vector Database will not function.")

# Sentence-transformers for embeddings
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    print("Warning: sentence-transformers not available. Using fallback embeddings.")


# =============================================================================
# CONFIGURATION
# =============================================================================

# Project root for data storage
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)  # Go up one level to project root

# Default paths
DEFAULT_DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DEFAULT_CHROMA_DIR = os.path.join(DEFAULT_DATA_DIR, "experience_db")

# Embedding model - using a lightweight model for speed
DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Number of similar tasks to retrieve for few-shot learning
DEFAULT_TOP_K = 2


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class TaskExperience:
    """
    Represents a single task experience stored in the vector database.
    
    Attributes:
        task_id: Unique identifier for the task
        user_request: The original user request text
        generated_code: The successful Python code that was generated
        domain: The domain (legal, accounting, data_analysis)
        task_type: The task type (visualization, document, spreadsheet)
        output_format: The output format (image, docx, xlsx, pdf)
        csv_headers: CSV column headers for context
    """
    task_id: str
    user_request: str
    generated_code: str
    domain: str
    task_type: str
    output_format: str
    csv_headers: List[str]


@dataclass
class FewShotExample:
    """
    Represents a few-shot example for LLM prompting.
    
    Attributes:
        user_request: The similar task's user request
        generated_code: The successful code from that task
        similarity_score: Cosine similarity score (0-1)
    """
    user_request: str
    generated_code: str
    similarity_score: float


# =============================================================================
# EXPERIENCE VECTOR DATABASE
# =============================================================================

class ExperienceVectorDB:
    """
    Vector database for storing and retrieving successful task experiences.
    
    This class provides:
    - Storage of successful task experiences with embeddings
    - Similarity search for finding relevant past tasks
    - Few-shot example generation for LLM prompting
    
    Usage:
        # Store a successful task
        db = ExperienceVectorDB()
        db.store_successful_task(
            task_id="task-123",
            user_request="Create a bar chart of sales data",
            generated_code="...python code...",
            domain="accounting",
            task_type="visualization",
            output_format="image"
        )
        
        # Get few-shot examples for a new task
        examples = db.query_similar_tasks(
            user_request="Create a pie chart of revenue",
            domain="accounting",
            top_k=2
        )
        
        # Use examples in system prompt
        system_prompt = db.build_few_shot_system_prompt(base_prompt, examples)
    """
    
    def __init__(
        self,
        persist_directory: str = DEFAULT_CHROMA_DIR,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        top_k: int = DEFAULT_TOP_K
    ):
        """
        Initialize the Experience Vector Database.
        
        Args:
            persist_directory: Directory to persist ChromaDB data
            embedding_model: Name of sentence-transformers model to use
            top_k: Default number of similar tasks to retrieve
        """
        self.persist_directory = persist_directory
        self.embedding_model = embedding_model
        self.top_k = top_k
        
        # Initialize components
        self._chroma_client = None
        self._collection = None
        self._embedding_model = None
        
        # Check availability
        if not CHROMADB_AVAILABLE:
            print("Error: ChromaDB is not installed. Install with: pip install chromadb")
            return
        
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            print("Error: sentence-transformers is not installed. Install with: pip install sentence-transformers")
            return
        
        # Initialize ChromaDB client
        self._initialize_chroma()
        
        # Initialize embedding model
        self._initialize_embedding_model()
    
    def _initialize_chroma(self):
        """Initialize ChromaDB client and collection."""
        try:
            # Create persist directory if it doesn't exist
            os.makedirs(self.persist_directory, exist_ok=True)
            
            # Initialize ChromaDB client with persistence
            self._chroma_client = chromadb.Client(Settings(
                persist_directory=self.persist_directory,
                anonymized_telemetry=False
            ))
            
            # Get or create the experience collection
            try:
                self._collection = self._chroma_client.get_collection("task_experiences")
                print(f"Experience Vector DB: Loaded existing collection with {self._collection.count()} experiences")
            except Exception:
                # Collection doesn't exist, create it
                self._collection = self._chroma_client.create_collection(
                    name="task_experiences",
                    metadata={"description": "Task experiences for few-shot learning"}
                )
                print("Experience Vector DB: Created new collection")
                
        except Exception as e:
            print(f"Error initializing ChromaDB: {e}")
            self._chroma_client = None
            self._collection = None
    
    def _initialize_embedding_model(self):
        """Initialize the sentence-transformers embedding model."""
        try:
            self._embedding_model = SentenceTransformer(self.embedding_model)
            print(f"Experience Vector DB: Loaded embedding model '{self.embedding_model}'")
        except Exception as e:
            print(f"Error loading embedding model: {e}")
            self._embedding_model = None
    
    def _get_embedding(self, text: str) -> List[float]:
        """
        Get embedding vector for text using sentence-transformers.
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats representing the embedding vector
        """
        if self._embedding_model is None:
            # Fallback: return zeros (shouldn't happen in practice)
            return [0.0] * 384  # MiniLM-L6-v2 outputs 384-dim vectors
        
        embedding = self._embedding_model.encode(text, show_progress_bar=False)
        return embedding.tolist()
    
    def store_successful_task(
        self,
        task_id: str,
        user_request: str,
        generated_code: str,
        domain: str,
        task_type: str = "visualization",
        output_format: str = "image",
        csv_headers: Optional[List[str]] = None
    ) -> bool:
        """
        Store a successful task experience in the vector database.
        
        This should be called when a task is marked as COMPLETED and approved.
        The user_request and generated_code are stored with embeddings for
        similarity search in future tasks.
        
        Args:
            task_id: Unique identifier for the task
            user_request: The original user request text
            generated_code: The successful Python code that was generated
            domain: The domain (legal, accounting, data_analysis)
            task_type: The task type (visualization, document, spreadsheet)
            output_format: The output format (image, docx, xlsx, pdf)
            csv_headers: Optional list of CSV column headers for context
            
        Returns:
            True if storage was successful, False otherwise
        """
        if self._collection is None or self._embedding_model is None:
            print("Error: ExperienceVectorDB not properly initialized")
            return False
        
        try:
            # Create the combined text for embedding (user request + context)
            combined_text = f"{user_request}"
            if csv_headers:
                combined_text += f" | Columns: {', '.join(csv_headers)}"
            
            # Get embedding
            embedding = self._get_embedding(combined_text)
            
            # Prepare metadata
            metadata = {
                "user_request": user_request,
                "generated_code": generated_code,
                "domain": domain,
                "task_type": task_type,
                "output_format": output_format,
                "csv_headers": json.dumps(csv_headers) if csv_headers else "[]"
            }
            
            # Store in ChromaDB
            self._collection.add(
                ids=[task_id],
                embeddings=[embedding],
                metadatas=[metadata],
                documents=[combined_text]
            )
            
            print(f"ExperienceVectorDB: Stored task {task_id} (domain: {domain}, type: {task_type})")
            return True
            
        except Exception as e:
            print(f"Error storing task experience: {e}")
            return False
    
    def query_similar_tasks(
        self,
        user_request: str,
        domain: Optional[str] = None,
        task_type: Optional[str] = None,
        top_k: Optional[int] = None
    ) -> List[FewShotExample]:
        """
        Query for similar past tasks based on user request.
        
        Uses semantic similarity search to find the most relevant past tasks
        that can be used as few-shot examples for the LLM.
        
        Args:
            user_request: The new task's user request
            domain: Optional domain filter (legal, accounting, data_analysis)
            task_type: Optional task type filter (visualization, document, spreadsheet)
            top_k: Number of similar tasks to return (defaults to self.top_k)
            
        Returns:
            List of FewShotExample objects sorted by similarity score
        """
        if self._collection is None or self._embedding_model is None:
            print("Error: ExperienceVectorDB not properly initialized")
            return []
        
        try:
            # Get number of results
            k = top_k or self.top_k
            
            # Build where clause for filtering
            where_clause = {}
            if domain:
                where_clause["domain"] = domain
            if task_type:
                where_clause["task_type"] = task_type
            
            # Get embedding for the query
            query_embedding = self._get_embedding(user_request)
            
            # Query ChromaDB
            if where_clause:
                results = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=k,
                    where=where_clause
                )
            else:
                results = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=k
                )
            
            # Parse results
            examples = []
            if results and results.get("ids") and len(results["ids"]) > 0:
                for i, task_id in enumerate(results["ids"][0]):
                    metadata = results["metadatas"][0][i]
                    distances = results.get("distances", [[]])[0]
                    
                    # Calculate similarity score (1 - distance, since ChromaDB uses cosine distance)
                    similarity_score = 1.0 - distances[i] if i < len(distances) else 0.0
                    
                    example = FewShotExample(
                        user_request=metadata.get("user_request", ""),
                        generated_code=metadata.get("generated_code", ""),
                        similarity_score=similarity_score
                    )
                    examples.append(example)
                    
            print(f"ExperienceVectorDB: Found {len(examples)} similar tasks for: {user_request[:50]}...")
            return examples
            
        except Exception as e:
            print(f"Error querying similar tasks: {e}")
            return []
    
    def build_few_shot_system_prompt(
        self,
        base_system_prompt: str,
        examples: Optional[List[FewShotExample]] = None,
        user_request: Optional[str] = None,
        domain: Optional[str] = None,
        top_k: Optional[int] = None
    ) -> str:
        """
        Build a system prompt with few-shot examples.
        
        This method either uses provided examples or automatically queries
        for similar tasks based on the user request and domain.
        
        Args:
            base_system_prompt: The base system prompt to enhance with examples
            examples: Optional pre-fetched examples (if not provided, will query)
            user_request: The user request (required if examples not provided)
            domain: The domain (optional, used for filtering)
            top_k: Number of examples to include
            
        Returns:
            Enhanced system prompt with few-shot examples
        """
        # Get examples if not provided
        if examples is None:
            if user_request is None:
                return base_system_prompt  # No examples to add
            
            examples = self.query_similar_tasks(
                user_request=user_request,
                domain=domain,
                top_k=top_k
            )
        
        # If no examples found, return base prompt
        if not examples:
            return base_system_prompt
        
        # Build few-shot section
        few_shot_section = "\n\n" + "="*60 + "\n"
        few_shot_section += "PREVIOUS SUCCESSFUL EXAMPLES (Use these as reference):\n"
        few_shot_section += "="*60 + "\n\n"
        
        for i, example in enumerate(examples, 1):
            few_shot_section += f"--- Example {i} (Similarity: {example.similarity_score:.2f}) ---\n"
            few_shot_section += f"User Request: {example.user_request}\n\n"
            few_shot_section += f"Successful Code:\n{example.generated_code}\n\n"
        
        few_shot_section += "="*60 + "\n"
        few_shot_section += "END OF EXAMPLES\n"
        few_shot_section += "="*60 + "\n\n"
        few_shot_section += "Use the examples above as reference when generating code for the new request.\n"
        
        # Combine base prompt with examples
        enhanced_prompt = base_system_prompt + few_shot_section
        
        return enhanced_prompt
    
    def get_experience_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the experience database.
        
        Returns:
            Dictionary with stats about stored experiences
        """
        if self._collection is None:
            return {
                "available": False,
                "error": "ChromaDB not initialized"
            }
        
        try:
            total_experiences = self._collection.count()
            
            # Get counts by domain
            # Note: This is approximate since ChromaDB doesn't support complex aggregations
            domains = {}
            
            return {
                "available": True,
                "total_experiences": total_experiences,
                "persist_directory": self.persist_directory,
                "embedding_model": self.embedding_model,
                "by_domain": domains
            }
        except Exception as e:
            return {
                "available": False,
                "error": str(e)
            }
    
    def clear_all(self) -> bool:
        """
        Clear all experiences from the database.
        
        WARNING: This deletes all stored experiences. Use with caution.
        
        Returns:
            True if successful, False otherwise
        """
        if self._collection is None:
            return False
        
        try:
            # Get all IDs and delete them
            all_ids = self._collection.get()["ids"]
            if all_ids:
                self._collection.delete(ids=all_ids)
            print("ExperienceVectorDB: Cleared all experiences")
            return True
        except Exception as e:
            print(f"Error clearing experiences: {e}")
            return False


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

# Global instance for easy access across the application
_experience_db: Optional[ExperienceVectorDB] = None


def get_experience_db() -> ExperienceVectorDB:
    """
    Get the global ExperienceVectorDB instance.
    
    Creates the instance if it doesn't exist (singleton pattern).
    
    Returns:
        The global ExperienceVectorDB instance
    """
    global _experience_db
    
    if _experience_db is None:
        try:
            _experience_db = ExperienceVectorDB()
        except Exception as e:
            print(f"Error creating ExperienceVectorDB: {e}")
            # Return a dummy instance that will fail gracefully
            _experience_db = None
    
    return _experience_db


def store_successful_task(
    task_id: str,
    user_request: str,
    generated_code: str,
    domain: str,
    task_type: str = "visualization",
    output_format: str = "image",
    csv_headers: Optional[List[str]] = None
) -> bool:
    """
    Convenience function to store a successful task.
    
    Args:
        task_id: Unique identifier for the task
        user_request: The original user request text
        generated_code: The successful Python code that was generated
        domain: The domain (legal, accounting, data_analysis)
        task_type: The task type
        output_format: The output format
        csv_headers: Optional list of CSV column headers
        
    Returns:
        True if storage was successful
    """
    db = get_experience_db()
    if db is None:
        print("Warning: ExperienceVectorDB not available, skipping task storage")
        return False
    
    return db.store_successful_task(
        task_id=task_id,
        user_request=user_request,
        generated_code=generated_code,
        domain=domain,
        task_type=task_type,
        output_format=output_format,
        csv_headers=csv_headers
    )


def query_similar_tasks(
    user_request: str,
    domain: Optional[str] = None,
    task_type: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K
) -> List[FewShotExample]:
    """
    Convenience function to query similar tasks.
    
    Args:
        user_request: The new task's user request
        domain: Optional domain filter
        task_type: Optional task type filter
        top_k: Number of similar tasks to return
        
    Returns:
        List of FewShotExample objects
    """
    db = get_experience_db()
    if db is None:
        print("Warning: ExperienceVectorDB not available, returning empty examples")
        return []
    
    return db.query_similar_tasks(
        user_request=user_request,
        domain=domain,
        task_type=task_type,
        top_k=top_k
    )


def build_few_shot_system_prompt(
    base_system_prompt: str,
    user_request: str,
    domain: Optional[str] = None,
    top_k: int = DEFAULT_TOP_K
) -> str:
    """
    Convenience function to build a system prompt with few-shot examples.
    
    Args:
        base_system_prompt: The base system prompt
        user_request: The user request to find similar tasks for
        domain: Optional domain for filtering
        top_k: Number of examples to include
        
    Returns:
        Enhanced system prompt with few-shot examples
    """
    db = get_experience_db()
    if db is None:
        return base_system_prompt
    
    return db.build_few_shot_system_prompt(
        base_system_prompt=base_system_prompt,
        user_request=user_request,
        domain=domain,
        top_k=top_k
    )


# =============================================================================
# MAIN / TEST
# =============================================================================

if __name__ == "__main__":
    # Test the Experience Vector Database
    print("=" * 60)
    print("Testing Experience Vector Database")
    print("=" * 60)
    
    # Check if dependencies are available
    if not CHROMADB_AVAILABLE:
        print("ERROR: ChromaDB not installed")
        print("Install with: pip install chromadb")
    else:
        print("✓ ChromaDB available")
    
    if not SENTENCE_TRANSFORMERS_AVAILABLE:
        print("ERROR: sentence-transformers not installed")
        print("Install with: pip install sentence-transformers")
    else:
        print("✓ sentence-transformers available")
    
    # Initialize the database
    print("\nInitializing Experience Vector Database...")
    db = ExperienceVectorDB()
    
    # Get stats
    stats = db.get_experience_stats()
    print(f"\nDatabase stats: {stats}")
    
    # Test storing a sample experience
    print("\n--- Testing store_successful_task ---")
    success = db.store_successful_task(
        task_id="test-task-001",
        user_request="Create a bar chart showing monthly sales",
        generated_code="import pandas as pd\nimport matplotlib.pyplot as plt\n# ... generated code ...",
        domain="accounting",
        task_type="visualization",
        output_format="image",
        csv_headers=["month", "sales", "expenses"]
    )
    print(f"Store result: {success}")
    
    # Test querying similar tasks
    print("\n--- Testing query_similar_tasks ---")
    examples = db.query_similar_tasks(
        user_request="Create a chart of quarterly revenue",
        domain="accounting",
        top_k=2
    )
    print(f"Found {len(examples)} similar tasks")
    for ex in examples:
        print(f"  - Similarity: {ex.similarity_score:.3f}")
        print(f"    Request: {ex.user_request[:50]}...")
    
    # Test building few-shot prompt
    print("\n--- Testing build_few_shot_system_prompt ---")
    base_prompt = "You are an expert data scientist."
    enhanced_prompt = db.build_few_shot_system_prompt(
        base_prompt,
        user_request="Create a chart of quarterly revenue",
        domain="accounting"
    )
    print(f"Original prompt length: {len(base_prompt)} chars")
    print(f"Enhanced prompt length: {len(enhanced_prompt)} chars")
    
    print("\n" + "=" * 60)
    print("Test complete!")
    print("=" * 60)
