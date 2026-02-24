import os
import json
import logging
from datetime import datetime
from typing import Optional

# Setup basic logging for the logger itself
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ExperienceLogger")

class ExperienceLogger:
    """
    Logs successful AI executions to build a fine-tuning dataset.
    Formats data into standard instruction/response JSONL format 
    suitable for Unsloth / Hugging Face training.
    """
    def __init__(self, dataset_path: str = "data/experience_dataset.jsonl"):
        self.dataset_path = dataset_path
        
        # Ensure the data directory exists
        os.makedirs(os.path.dirname(self.dataset_path), exist_ok=True)

    def log_success(self, task) -> bool:
        """
        Extracts successful planning and execution data from a completed task
        and appends it to the dataset. Strips PII.
        """
        try:
            # 1. Skip if there's no work plan (we only want to train on planned successes)
            if not task.work_plan:
                return False

            # 2. Extract and format the input prompt (The "Instruction")
            # Notice we DO NOT include task.client_email to protect PII
            instruction = f"Domain: {task.domain}\nTask: {task.title}\nDescription: {task.description}"
            
            # 3. Extract the successful output (The "Response")
            # We train the local model to output this exact JSON work plan structure
            try:
                plan_dict = json.loads(task.work_plan)
                # Pretty-print the JSON so the model learns formatting
                response = json.dumps(plan_dict, indent=2) 
            except json.JSONDecodeError:
                response = task.work_plan

            # 4. Format for Unsloth / HuggingFace standard (Alpaca/ShareGPT style)
            dataset_entry = {
                "instruction": "You are an expert AI agent. Create a comprehensive work plan for the following task.",
                "input": instruction,
                "output": response,
                "metadata": {
                    "domain": task.domain,
                    "complexity": task.is_high_value,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }

            # 5. Append to JSONL file
            with open(self.dataset_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(dataset_entry) + "\n")
                
            logger.info(f"Successfully logged experience for task {task.id} to {self.dataset_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to log experience for task {task.id}: {str(e)}")
            return False

# Global instance
experience_logger = ExperienceLogger()
