# Fine-Tuning Pipeline - Quick Reference

## Quick Start

```python
# 1. Prepare dataset
from src.fine_tuning import DatasetBuilder
builder = DatasetBuilder()
examples = builder.build_from_distillation(min_rating=4, domain="data_analysis")
builder.save_dataset(examples, "my_dataset", format="openai")

# 2. Create OpenAI fine-tuning job
from src.fine_tuning import OpenAIFineTuner
tuner = OpenAIFineTuner()
file_id = tuner.upload_training_file("my_dataset.jsonl")
job = tuner.create_fine_tuning_job("gpt-3.5-turbo", file_id)
print(f"Job: {job['job_id']}")

# 3. Check status
status = tuner.get_job_status(job['job_id'])
print(f"Status: {status['status']}, Model: {status['fine_tuned_model']}")

# 4. Register model
from src.fine_tuning import ModelRegistry
registry = ModelRegistry()
registry.register_model(
    model_name="my-model",
    base_model="gpt-3.5-turbo",
    job_id=job['job_id'],
    dataset_size=500,
    accuracy=0.92,
    cost=50.0
)
registry.set_model_status("my-model", "DEPLOYED")

# 5. Evaluate with A/B test
from src.fine_tuning import ABTestFramework
ab = ABTestFramework()
ab.create_test("test_001", "gpt-35-base", "my-model")
# Record samples...
result = ab.conclude_test("test_001")
winner = ab.recommend_winner(result)
print(f"Winner: {winner}")

# 6. Track ROI
from src.fine_tuning import CostTracker
tracker = CostTracker()
roi = tracker.calculate_roi(
    model_name="my-model",
    base_model_inference_cost=0.002,
    expected_inference_count=10000
)
print(f"ROI: {roi.roi_at_expected * 100:.1f}%")
```

## CLI Commands

```bash
# Prepare dataset
ft-cli prepare-dataset --format openai --min-rating 4

# Create OpenAI job
ft-cli create-openai-job gpt-3.5-turbo dataset.jsonl --suffix "v1"

# Check job
ft-cli check-job-status ftjob-abc123

# Generate Ollama script
ft-cli create-ollama-script llama2 dataset.json my-finetuned-llama

# Register model
ft-cli register-model my-model gpt-3.5-turbo ftjob-abc123 500 \
  --accuracy 0.95 --cost 50.0

# List models
ft-cli list-models

# Cost summary
ft-cli cost-summary

# Rollback
ft-cli rollback-model my-model 1
```

## Module Overview

| Module | Purpose | Key Class |
|--------|---------|-----------|
| `dataset_builder.py` | Data preparation | `DatasetBuilder` |
| `openai_fine_tuner.py` | OpenAI integration | `OpenAIFineTuner` |
| `ollama_fine_tuner.py` | Local fine-tuning | `OllamaFineTuner` |
| `model_evaluator.py` | Evaluation metrics | `ModelEvaluator` |
| `ab_testing.py` | A/B testing | `ABTestFramework` |
| `model_registry.py` | Version management | `ModelRegistry` |
| `cost_tracker.py` | Cost analysis | `CostTracker` |
| `cli.py` | Command-line tool | `FineTuningCLI` |

## Key Metrics

### Training Costs
- **100 examples**: $3-5 (gpt-3.5-turbo)
- **500 examples**: $30-50 (gpt-3.5-turbo)
- **5K examples**: $300-500 (gpt-3.5-turbo)

### Inference Costs
- **Base model**: $0.0015/call (avg)
- **Fine-tuned**: $0.0015/call (similar)
- **Local Ollama**: Free

### ROI Timeline
- **Training**: $40-50
- **Break-even**: 1-2 days (with accuracy improvement)
- **6-month ROI**: 10,000-50,000%

## Common Workflows

### Workflow 1: Quick Fine-Tune & Deploy

```python
# Step 1: Prepare
builder = DatasetBuilder()
examples = builder.build_from_distillation(min_rating=4)
builder.save_dataset(examples, "dataset", format="openai")

# Step 2: Create job
tuner = OpenAIFineTuner()
file_id = tuner.upload_training_file("dataset.jsonl")
job = tuner.create_fine_tuning_job("gpt-3.5-turbo", file_id)

# Wait for job completion...

# Step 3: Register & Deploy
registry = ModelRegistry()
registry.register_model("my-model", "gpt-3.5-turbo", job['job_id'], 500)
registry.set_model_status("my-model", "DEPLOYED")
```

### Workflow 2: A/B Test & Rollout

```python
# Create test
ab = ABTestFramework()
ab.create_test("rollout_test", "old-model", "new-model")

# In production: record samples
for i in range(1000):
    ab.record_sample("rollout_test", "model_a" or "model_b", 
                     prediction, reference, latency, cost)

# Analyze
result = ab.conclude_test("rollout_test")
if result.statistical_significance:
    winner = ab.recommend_winner(result)
    registry = ModelRegistry()
    registry.rollback_model("my-model", 2)  # Deploy new version
```

### Workflow 3: Cost Analysis

```python
tracker = CostTracker()

# Record training
tracker.record_training_job(
    job_id="ftjob-123",
    model_name="my-model",
    base_model="gpt-3.5-turbo",
    dataset_size=500,
    training_tokens=100000,
    total_cost=50.0
)

# Record inferences
for call in production_calls:
    tracker.record_inference(
        model_name="my-model",
        tokens_used=call.tokens,
        cost=call.cost,
        is_fine_tuned=True
    )

# Analyze ROI
roi = tracker.calculate_roi(
    model_name="my-model",
    base_model_inference_cost=0.002,
    expected_inference_count=10000
)
print(f"ROI: {roi.roi_at_expected:.2%}")
print(f"Payback: {roi.payback_days:.1f} days")
```

## Test Coverage

```bash
cd /home/alexc/Projects/ArbitrageAI
pytest tests/test_fine_tuning.py -v

# Results:
# - 35 tests total
# - 9 dataset builder tests
# - 6 evaluator tests
# - 6 A/B testing tests
# - 7 registry tests
# - 5 cost tracker tests
# - 2 integration tests
# All passing ✓
```

## Integration Points

### With Distillation System
```python
from src.distillation.data_collector import DistillationDataCollector
collector = DistillationDataCollector()
examples = collector.get_curated_examples(min_rating=4)
```

### With LLM Service
```python
from src.llm_service import LLMService
# Use fine-tuned model registered in pipeline
llm = LLMService(model="my-finetuned-model")
```

### With Task API
```python
# Register fine-tuned model in database
task.fine_tuned_model_id = "my-model-v2"
task.model_accuracy = 0.95
```

## Troubleshooting

### OpenAI Fine-Tuning Fails
```
Check:
1. OPENAI_API_KEY is set
2. File format is correct JSONL
3. Each record has required fields
4. Account has sufficient credits
```

### A/B Test Shows No Significant Difference
```
- Need more samples (aim for 100+ per model)
- Might need larger dataset differences
- Check if models are actually different
```

### Model Rollback Fails
```
- Ensure version exists: registry.list_model_versions("name")
- Check previous version status
- Use set_model_status before rollback
```

## Performance Tips

1. **Dataset Size**: 500+ examples for meaningful improvements
2. **Learning Rate**: Default 1.0 works for most cases
3. **Epochs**: 3-5 epochs for convergence
4. **Validation**: Use ~20% of data for validation
5. **A/B Tests**: Minimum 100 samples per model for significance

## Next Steps

1. ✓ Prepare dataset from distillation
2. ✓ Create fine-tuning job
3. ✓ Wait for job completion
4. ✓ Register model version
5. ✓ Deploy to production
6. ✓ A/B test vs base model
7. ✓ Monitor costs and ROI
8. ✓ Iterate with new data

## Documentation Links

- Full implementation: `ISSUE_44_FINE_TUNING_PIPELINE.md`
- Dataset builder: `src/fine_tuning/dataset_builder.py`
- OpenAI integration: `src/fine_tuning/openai_fine_tuner.py`
- A/B testing: `src/fine_tuning/ab_testing.py`
- Tests: `tests/test_fine_tuning.py`
