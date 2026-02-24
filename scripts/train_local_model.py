#!/usr/bin/env python3
"""
Local Model Fine-tuning Script using Unsloth

This script fine-tunes a local model (Llama 3.2 8B) using QLoRA on your 
collected dataset of successful cloud model outputs.

Usage:
    python scripts/train_local_model.py --domain legal --epochs 3
    
Requirements:
    - GPU with 24GB+ VRAM (RTX 3090/4090 recommended)
    - CUDA installed
    - Unsloth package
    
The Concept:
    1. Collect 500+ successful examples from GPT-4o (done automatically)
    2. Run this script to fine-tune Llama 3.2 8B
    3. Update TASK_MODEL_MAP to route to your fine-tuned model
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Default paths
DISTILLATION_DIR = PROJECT_ROOT / "data" / "distillation"
DEFAULT_MODEL = "unsloth/llama-3.2-8b-bnb-4bit"  # Unsloth's optimized Llama 3.2 8B


def check_gpu_availability():
    """Check if GPU is available for training."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            gpu_info = result.stdout.strip()
            print(f"GPU Available: {gpu_info}")
            return True
        else:
            return False
    except FileNotFoundError:
        print("nvidia-smi not found. Make sure CUDA is installed.")
        return False


def load_dataset(domain: str = None, min_rating: int = 4):
    """
    Load the curated dataset for training.
    
    Args:
        domain: Optional domain filter
        min_rating: Minimum rating to include
        
    Returns:
        List of training examples
    """
    from src.distillation import DistillationDatasetManager
    
    manager = DistillationDatasetManager()
    examples = manager.load_examples(
        domain=domain,
        min_rating=min_rating
    )
    
    return examples


def prepare_training_data(examples: list, output_path: str = None):
    """
    Prepare training data in Alpaca format for Unsloth.
    
    Args:
        examples: List of examples from the dataset
        output_path: Path to save the training data
        
    Returns:
        Path to the prepared training data
    """
    if output_path is None:
        output_path = DISTILLATION_DIR / "training_data.json"
    
    # Convert to Alpaca format
    training_data = []
    for ex in examples:
        training_data.append({
            "instruction": ex["prompt"],
            "output": ex["response"],
            "input": ""
        })
    
    with open(output_path, 'w') as f:
        json.dump(training_data, f, indent=2)
    
    print(f"Prepared {len(training_data)} examples for training")
    return str(output_path)


def run_fine_tuning(
    data_path: str,
    output_dir: str,
    model: str = DEFAULT_MODEL,
    epochs: int = 3,
    rank: int = 16,
    alpha: int = 32,
    learning_rate: float = 2e-4,
    batch_size: int = 4,
    gradient_steps: int = 4,
    max_seq_length: int = 2048,
):
    """
    Run the QLoRA fine-tuning using Unsloth.
    
    Args:
        data_path: Path to training data
        output_dir: Directory to save the fine-tuned model
        model: Base model to fine-tune
        epochs: Number of training epochs
        rank: LoRA rank
        alpha: LoRA alpha
        learning_rate: Learning rate
        batch_size: Per-device batch size
        gradient_steps: Gradient accumulation steps
        max_seq_length: Maximum sequence length
    """
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Build the training command
    cmd = [
        "python", "-m", "unsloth.train",
        "--data", data_path,
        "--model", model,
        "--output", output_dir,
        "--epochs", str(epochs),
        "--rank", str(rank),
        "--alpha", str(alpha),
        "--learning_rate", str(learning_rate),
        "--batch_size", str(batch_size),
        "--gradient_steps", str(gradient_steps),
        "--max_seq_length", str(max_seq_length),
        "--use_gradient_checkpointing",
        "--use_fp16",
    ]
    
    print("=" * 60)
    print("Starting QLoRA Fine-tuning with Unsloth")
    print("=" * 60)
    print(f"Model: {model}")
    print(f"Data: {data_path}")
    print(f"Epochs: {epochs}")
    print(f"LoRA Rank: {rank}, Alpha: {alpha}")
    print(f"Learning Rate: {learning_rate}")
    print(f"Batch Size: {batch_size} x {gradient_steps} = {batch_size * gradient_steps}")
    print("=" * 60)
    
    # Run training
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print("\n✓ Fine-tuning completed successfully!")
        return True
    else:
        print("\n✗ Fine-tuning failed!")
        return False


def export_to_ollama(output_dir: str, model_name: str = "distilled-llama3.2"):
    """
    Export the fine-tuned model to Ollama format.
    
    Args:
        output_dir: Directory containing the fine-tuned model
        model_name: Name for the Ollama model
        
    Returns:
        Path to the exported model
    """
    # Use Unsloth's export function
    cmd = [
        "python", "-m", "unsloth.export_ollama",
        "--model", output_dir,
        "--name", model_name,
    ]
    
    print("\nExporting to Ollama format...")
    result = subprocess.run(cmd)
    
    if result.returncode == 0:
        print(f"✓ Model exported as '{model_name}'")
        return f"{output_dir}/{model_name}"
    else:
        print("✗ Export failed, trying alternative method...")
        return None


def generate_ollama_modelfile(
    model_dir: str,
    model_name: str,
    template_type: str = "chat"
):
    """
    Generate a Modelfile for Ollama.
    
    Args:
        model_dir: Directory containing the model
        model_name: Name of the model
        template_type: Template type (chat or completion)
        
    Returns:
        Path to the Modelfile
    """
    modelfile_content = f"""FROM {model_dir}

# Set temperature for consistent outputs
PARAMETER temperature 0.3
PARAMETER top_p 0.9

# Set system prompt for the fine-tuned model
SYSTEM \"\"\"You are an expert data visualization and document generation assistant.
You generate high-quality Python code for data analysis, visualizations, 
and document creation from CSV data.

Your outputs should be:
- Clean, executable Python code
- Professional visualizations with matplotlib
- Well-formatted documents with python-docx
- Properly structured Excel spreadsheets with openpyxl

Always output complete, runnable code that reads from a 'csv_data' variable
and produces the requested output format.\"\"\"
"""
    
    modelfile_path = os.path.join(model_dir, "Modelfile")
    with open(modelfile_path, 'w') as f:
        f.write(modelfile_content)
    
    print(f"✓ Created Modelfile at: {modelfile_path}")
    return modelfile_path


def update_task_model_map(
    model_name: str,
    domains: list = None
):
    """
    Update the TASK_MODEL_MAP in the environment/.env to route to the fine-tuned model.
    
    Args:
        model_name: Name of the fine-tuned model in Ollama
        domains: List of domains to route to the fine-tuned model
    """
    if domains is None:
        domains = ["legal", "accounting", "data_analysis"]
    
    # Read current .env or create one
    env_path = PROJECT_ROOT / ".env"
    
    current_content = ""
    if env_path.exists():
        with open(env_path, 'r') as f:
            current_content = f.read()
    
    # Check if TASK_MODEL_MAP exists
    if "TASK_MODEL_MAP=" in current_content:
        # Update existing
        print("Please manually update your TASK_MODEL_MAP in .env")
    else:
        # Add new configuration
        task_model_json = json.dumps({
            domain: model_name for domain in domains
        })
        
        new_lines = f"""
# Local Model Distillation - Fine-tuned model configuration
# Generated by train_local_model.py
DISTILLED_MODEL_NAME={model_name}
TASK_MODEL_MAP={task_model_json}
"""
        
        with open(env_path, 'a') as f:
            f.write(new_lines)
        
        print("✓ Updated .env with fine-tuned model configuration")
        print(f"  Model: {model_name}")
        print(f"  Domains: {domains}")


def print_instructions(model_path: str):
    """Print instructions for using the fine-tuned model."""
    print("\n" + "=" * 60)
    print("FINE-TUNING COMPLETE!")
    print("=" * 60)
    print(f"""
Next steps:

1. Import the model into Ollama:
   ollama create {model_path}
   
2. Or use it directly with the Ollama API:
   ollama serve --model {model_path}

3. Update your configuration:
   - Set LOCAL_MODEL={model_path} in .env
   - Or update TASK_MODEL_MAP to route specific domains

4. Test the model:
   python -c "from src.llm_service import LLMService; llm = LLMService.for_task('legal')"

Note: The fine-tuned model should now handle tasks that previously
required GPT-4o, saving significantly on API costs!
""")
    print("=" * 60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Fine-tune local model using Unsloth with your distillation dataset"
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=None,
        help="Domain to fine-tune for (legal, accounting, data_analysis). If not specified, trains on all domains."
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Number of training epochs (default: 3)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"Base model to fine-tune (default: {DEFAULT_MODEL})"
    )
    parser.add_argument(
        "--rank",
        type=int,
        default=16,
        help="LoRA rank (default: 16)"
    )
    parser.add_argument(
        "--alpha",
        type=int,
        default=32,
        help="LoRA alpha (default: 32)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Per-device batch size (default: 4)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output directory for the fine-tuned model"
    )
    parser.add_argument(
        "--skip-training",
        action="store_true",
        help="Skip training and just prepare data"
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Only export to Ollama (skip training)"
    )
    
    args = parser.parse_args()
    
    # Check GPU availability
    if not check_gpu_availability():
        print("\n⚠️  WARNING: No GPU detected. Fine-tuning requires a GPU with 24GB+ VRAM.")
        print("On CPU, this would take very long. Consider using Google Colab with GPU.")
        
        response = input("\nContinue anyway? (y/n): ")
        if response.lower() != 'y':
            return
    
    # Load dataset
    print("\n📊 Loading dataset...")
    examples = load_dataset(domain=args.domain)
    
    if len(examples) < 100:
        print(f"\n⚠️  WARNING: Only {len(examples)} examples found.")
        print("For best results, collect at least 500 high-quality examples.")
        
        response = input("Continue with less data? (y/n): ")
        if response.lower() != 'y':
            return
    
    print(f"✓ Loaded {len(examples)} examples")
    
    # Prepare training data
    print("\n📝 Preparing training data...")
    data_path = prepare_training_data(examples)
    
    if args.skip_training:
        print("\n✓ Data preparation complete (skipping training)")
        return
    
    # Set up output directory
    if args.output is None:
        model_name = f"distilled-{args.domain or 'all'}-llama3.2"
        output_dir = DISTILLATION_DIR / "models" / model_name
    else:
        output_dir = Path(args.output)
    
    # Run fine-tuning
    print("\n🚀 Starting fine-tuning...")
    success = run_fine_tuning(
        data_path=data_path,
        output_dir=str(output_dir),
        model=args.model,
        epochs=args.epochs,
        rank=args.rank,
        alpha=args.alpha,
        batch_size=args.batch_size,
    )
    
    if not success:
        print("\n✗ Fine-tuning failed!")
        return
    
    # Export to Ollama
    model_name = f"distilled-{args.domain or 'general'}-llama3.2"
    model_path = export_to_ollama(str(output_dir), model_name)
    
    if model_path is None:
        # Create Modelfile as fallback
        modelfile = generate_ollama_modelfile(str(output_dir), model_name)
        model_path = modelfile
    
    # Update configuration
    update_task_model_map(model_name, domains=[args.domain] if args.domain else None)
    
    # Print final instructions
    print_instructions(model_name)


if __name__ == "__main__":
    main()
