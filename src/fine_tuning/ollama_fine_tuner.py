"""
Ollama Fine-Tuning Integration

Handles fine-tuning with local Ollama models using Unsloth.
"""

import json
import os
import subprocess
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class OllamaFineTuner:
    """
    Fine-tunes Ollama models locally using Unsloth.

    Supports:
    - Llama 2, Llama 3.x
    - Mistral
    - Custom models

    Features:
    - Prepare datasets for Unsloth
    - Launch fine-tuning process
    - Monitor training progress
    - Load fine-tuned models into Ollama
    """

    def __init__(self, ollama_base_url: str = "http://localhost:11434"):
        """
        Initialize Ollama fine-tuner.

        Args:
            ollama_base_url: Base URL for Ollama service
        """
        self.ollama_base_url = ollama_base_url
        self.output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data",
            "ollama_finetuning",
        )
        os.makedirs(self.output_dir, exist_ok=True)

    def prepare_dataset_for_unsloth(
        self, examples: List[Dict[str, Any]], output_path: Optional[str] = None
    ) -> str:
        """
        Prepare dataset in Unsloth format.

        Args:
            examples: List of training examples
            output_path: Path to save dataset

        Returns:
            Path to prepared dataset
        """
        if output_path is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(self.output_dir, f"unsloth_dataset_{timestamp}.json")

        # Convert to Alpaca format for Unsloth
        training_data = [
            {
                "instruction": ex.get("prompt", ""),
                "output": ex.get("response", ""),
                "input": "",
            }
            for ex in examples
        ]

        with open(output_path, "w") as f:
            json.dump(training_data, f, indent=2)

        logger.info(f"Prepared Unsloth dataset: {output_path} ({len(training_data)} examples)")
        return output_path

    def create_fine_tuning_config(
        self,
        base_model: str,
        dataset_path: str,
        output_model_name: str,
        num_epochs: int = 3,
        learning_rate: float = 0.0005,
        batch_size: int = 4,
    ) -> Dict[str, Any]:
        """
        Create a fine-tuning configuration for Unsloth.

        Args:
            base_model: Base model name (e.g., "llama2", "mistral")
            dataset_path: Path to training dataset
            output_model_name: Name for fine-tuned model
            num_epochs: Number of training epochs
            learning_rate: Learning rate
            batch_size: Batch size for training

        Returns:
            Configuration dictionary
        """
        config = {
            "base_model": base_model,
            "dataset_path": dataset_path,
            "output_model_name": output_model_name,
            "num_epochs": num_epochs,
            "learning_rate": learning_rate,
            "batch_size": batch_size,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        config_path = os.path.join(
            self.output_dir, f"{output_model_name}_config.json"
        )
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        logger.info(f"Created fine-tuning config: {config_path}")
        return config

    def generate_unsloth_script(
        self,
        base_model: str,
        dataset_path: str,
        output_model_name: str,
        num_epochs: int = 3,
        learning_rate: float = 0.0005,
        batch_size: int = 4,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Generate a Python script to run Unsloth fine-tuning.

        Args:
            base_model: Base model name
            dataset_path: Path to training dataset
            output_model_name: Name for fine-tuned model
            num_epochs: Number of training epochs
            learning_rate: Learning rate
            batch_size: Batch size
            output_path: Path to save script

        Returns:
            Path to generated script
        """
        if output_path is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_path = os.path.join(
                self.output_dir, f"finetune_{output_model_name}_{timestamp}.py"
            )

        script = f'''#!/usr/bin/env python3
"""
Auto-generated Unsloth Fine-Tuning Script
Generated: {datetime.now(timezone.utc).isoformat()}
"""

from unsloth import FastLanguageModel
import torch
from datasets import load_dataset
from transformers import TrainingArguments, EarlyStoppingCallback
from trl import SFTTrainer
import json

# Configuration
BASE_MODEL = "{base_model}"
DATASET_PATH = "{dataset_path}"
OUTPUT_MODEL_NAME = "{output_model_name}"
NUM_EPOCHS = {num_epochs}
LEARNING_RATE = {learning_rate}
BATCH_SIZE = {batch_size}

# Load base model
print(f"Loading base model: {{BASE_MODEL}}")
max_seq_length = 2048
dtype = None  # Auto detect
load_in_4bit = True

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL,
    max_seq_length=max_seq_length,
    dtype=dtype,
    load_in_4bit=load_in_4bit,
)

# Prepare for training
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    lora_alpha=16,
    lora_dropout=0.05,
    bias="none",
    use_gradient_checkpointing="unsloth",
    use_rslora=False,
)

# Load dataset
print(f"Loading dataset: {{DATASET_PATH}}")
with open(DATASET_PATH, 'r') as f:
    data = json.load(f)

dataset = load_dataset(
    "json",
    data_files={{"train": DATASET_PATH}},
    split="train",
)

# Define training arguments
training_args = TrainingArguments(
    output_dir=f"./models/{{OUTPUT_MODEL_NAME}}",
    num_train_epochs=NUM_EPOCHS,
    per_device_train_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=4,
    warmup_steps=5,
    learning_rate=LEARNING_RATE,
    fp16=not torch.cuda.is_available(),
    bf16=torch.cuda.is_available(),
    logging_steps=10,
    optim="adamw_8bit",
    weight_decay=0.01,
    lr_scheduler_type="linear",
    seed=42,
    save_strategy="steps",
    save_steps=50,
    eval_strategy="steps",
    eval_steps=50,
    load_best_model_at_end=True,
)

# Create trainer
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    args=training_args,
    train_dataset=dataset,
    max_seq_length=max_seq_length,
    dataset_text_field="text",
    packing=False,
    callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
)

# Train
print("Starting training...")
trainer.train()

# Save model
print(f"Saving fine-tuned model...")
model.save_pretrained(f"./models/{{OUTPUT_MODEL_NAME}}/final")
tokenizer.save_pretrained(f"./models/{{OUTPUT_MODEL_NAME}}/final")

print(f"Fine-tuning complete! Model saved to ./models/{{OUTPUT_MODEL_NAME}}/final")
'''

        with open(output_path, "w") as f:
            f.write(script)

        # Make script executable
        os.chmod(output_path, 0o755)

        logger.info(f"Generated Unsloth script: {output_path}")
        return output_path

    def estimate_training_time(
        self, num_examples: int, num_epochs: int = 3, gpu_type: str = "a100"
    ) -> Dict[str, Any]:
        """
        Estimate fine-tuning time based on dataset size and GPU.

        Args:
            num_examples: Number of training examples
            num_epochs: Number of training epochs
            gpu_type: GPU type (a100, v100, a10, cpu)

        Returns:
            Time estimate dictionary
        """
        # Tokens per example (average)
        tokens_per_example = 200

        # GPU throughput (examples/second)
        throughput = {
            "a100": 100,
            "v100": 50,
            "a10": 30,
            "cpu": 5,
            "m1": 20,
        }

        gpu_throughput = throughput.get(gpu_type, 50)

        total_tokens = num_examples * tokens_per_example * num_epochs
        total_examples = num_examples * num_epochs

        estimated_seconds = total_examples / gpu_throughput
        estimated_minutes = estimated_seconds / 60
        estimated_hours = estimated_minutes / 60

        return {
            "num_examples": num_examples,
            "num_epochs": num_epochs,
            "total_examples": total_examples,
            "total_tokens": total_tokens,
            "gpu_type": gpu_type,
            "estimated_seconds": estimated_seconds,
            "estimated_minutes": estimated_minutes,
            "estimated_hours": estimated_hours,
        }

    def create_ollama_modelfile(
        self,
        model_path: str,
        model_name: str,
        system_prompt: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """
        Create an Ollama Modelfile for a fine-tuned model.

        Args:
            model_path: Path to fine-tuned model
            model_name: Name for the Ollama model
            system_prompt: Optional system prompt
            output_path: Path to save Modelfile

        Returns:
            Path to Modelfile
        """
        if output_path is None:
            output_path = os.path.join(self.output_dir, f"Modelfile_{model_name}")

        modelfile = f"""FROM {model_path}

# Set model name
PARAMETER model_name {model_name}
"""

        if system_prompt:
            modelfile += f'\nSYSTEM "{system_prompt}"\n'

        with open(output_path, "w") as f:
            f.write(modelfile)

        logger.info(f"Created Ollama Modelfile: {output_path}")
        return output_path
