# Issue #44: Fine-Tuning Pipeline for Custom Models

## Overview

Successfully implemented a comprehensive fine-tuning pipeline for task-specific models with full support for OpenAI fine-tuning APIs and local Ollama fine-tuning. The pipeline includes dataset preparation, training management, evaluation, A/B testing, model versioning, cost tracking, and ROI analysis.

## Pipeline Components

### 1. **Dataset Builder** (`src/fine_tuning/dataset_builder.py`)
Prepares training data from distillation history with quality filtering.

**Features:**
- Load examples from distillation collector
- Filter by domain, task type, and rating (1-5 scale)
- Validate dataset completeness and quality
- Export in multiple formats:
  - **OpenAI format**: JSONL with `messages` array (user/assistant roles)
  - **Alpaca format**: JSON with instruction/output/input fields
  - **JSONL format**: Raw records one-per-line
- Train/test split (configurable ratio)
- Dataset statistics (domains, task types, ratings, avg lengths)

**Key Methods:**
```python
build_from_distillation(min_rating=4, domain=None)  # Load from collector
validate_examples(examples)  # Quality validation
to_openai_format(examples)   # OpenAI format
to_alpaca_format(examples)   # Alpaca format
save_dataset(examples, filename, format)  # Save to file
split_train_test(examples, train_ratio)  # Train/test split
get_dataset_stats(examples)   # Statistics
```

**Dataset Size Handling:**
- Minimum 500 examples recommended for training
- Validates prompt (≥10 chars) and response (≥20 chars)
- Supports filtering by:
  - Domain: coding, data_analysis, finance, legal, etc.
  - Task type: code_generation, visualization, summarization, etc.
  - Rating: 1-5 scale (configurable minimum)

### 2. **OpenAI Fine-Tuner** (`src/fine_tuning/openai_fine_tuner.py`)
Manages fine-tuning jobs via OpenAI API.

**Supported Models:**
- `gpt-3.5-turbo`
- `gpt-4o-mini`

**Features:**
- Upload training/validation files to OpenAI
- Create fine-tuning jobs with configurable parameters
- Monitor job status (QUEUED, IN_PROGRESS, SUCCEEDED, FAILED)
- Cancel jobs
- List recent jobs
- Delete fine-tuned models
- Cost estimation

**Pricing (Built-in):**
- gpt-3.5-turbo: $0.003 per 1K input, $0.006 per 1K output tokens
- gpt-4o-mini: $0.015 per 1K input, $0.06 per 1K output tokens

**Key Methods:**
```python
upload_training_file(filepath) -> file_id
create_fine_tuning_job(model, training_file_id, learning_rate_multiplier=1.0)
get_job_status(job_id)
cancel_job(job_id)
list_jobs(limit=10)
estimate_cost(training_tokens, model)
delete_fine_tuned_model(model_id)
```

**Cost Example:**
```
100,000 training tokens on gpt-3.5-turbo:
- Input tokens: 80,000 @ $0.003/1K = $0.24
- Output tokens: 20,000 @ $0.006/1K = $0.12
- Total: ~$0.36 for dataset
```

### 3. **Ollama Fine-Tuner** (`src/fine_tuning/ollama_fine_tuner.py`)
Manages local fine-tuning with Unsloth framework.

**Supported Models:**
- Llama 2, Llama 3.x
- Mistral
- Custom models

**Features:**
- Prepare datasets in Unsloth format
- Generate Unsloth fine-tuning Python scripts
- Create fine-tuning configurations
- Estimate training time by GPU type
- Generate Ollama Modelfiles

**GPU Support:**
- A100: ~100 examples/sec
- V100: ~50 examples/sec
- A10: ~30 examples/sec
- CPU: ~5 examples/sec
- M1/M2: ~20 examples/sec

**Key Methods:**
```python
prepare_dataset_for_unsloth(examples, output_path)
create_fine_tuning_config(base_model, dataset_path, output_model_name)
generate_unsloth_script(base_model, dataset_path, output_model_name)
estimate_training_time(num_examples, num_epochs, gpu_type)
create_ollama_modelfile(model_path, model_name, system_prompt)
```

### 4. **Model Evaluator** (`src/fine_tuning/model_evaluator.py`)
Evaluates model performance on test sets.

**Evaluation Metrics:**
- **Accuracy**: Percentage of correct predictions
- **Precision/Recall/F1**: For classification tasks
- **Latency**: Average inference time (ms)
- **Cost per Inference**: Actual cost tracking

**Evaluation Modes:**
- **Exact Match**: Direct string comparison
- **Substring Match**: Reference contains prediction

**Key Methods:**
```python
evaluate_exact_match(predictions, references, model_name, model_type)
evaluate_substring_match(predictions, references, model_name, model_type)
compare_models(base_result, finetuned_result)  # Side-by-side comparison
calculate_roi(base_cost, finetuned_cost, accuracy_improvement, inference_count)
get_results_summary()  # Summary of all evaluations
```

**Comparison Example:**
```
Base Model vs Fine-Tuned:
- Accuracy: 85% → 92% (+7%)
- Latency: 200ms → 150ms (-25%)
- Cost/call: $0.002 → $0.0015 (-25%)
```

### 5. **A/B Testing Framework** (`src/fine_tuning/ab_testing.py`)
Compares models in production with statistical significance testing.

**Features:**
- Create A/B tests (model_a as control, model_b as variant)
- Record samples from production inference
- Calculate metrics per model
- Statistical significance testing (chi-squared)
- Automatic winner recommendation
- Confidence level tracking

**Statistical Testing:**
- Chi-squared test for significant differences
- Configurable alpha level (default 0.05)
- Critical Z-score: 1.96 (95% confidence)

**Winner Recommendation:**
Weighted scoring:
- 60% Accuracy
- 20% Latency (inverse)
- 20% Cost (inverse)

**Key Methods:**
```python
create_test(test_id, model_a, model_b)
record_sample(test_id, model, prediction, reference, latency_ms, cost)
conclude_test(test_id, alpha=0.05)  # Finalize and analyze
recommend_winner(test_result)  # Best model
get_test_results(test_id)
```

**Test Lifecycle:**
```
1. create_test("test_001", "base-gpt35", "finetuned-gpt35")
2. record_sample(...) × 100+ calls per model
3. conclude_test("test_001")  # Get results
4. recommend_winner(result)  # Winner: finetuned-gpt35
5. Deploy winner
```

### 6. **Model Registry** (`src/fine_tuning/model_registry.py`)
Tracks model versions, metadata, and deployment status.

**Features:**
- Register fine-tuned models with versions
- Track base model, dataset size, accuracy, cost
- Set model status (READY, DEPLOYED, ARCHIVED, FAILED)
- Rollback to previous versions
- Get deployment status
- Cost summaries per model

**Status Lifecycle:**
```
TRAINING → READY → DEPLOYED
           ↓
          (Bad) → FAILED
```

**Key Methods:**
```python
register_model(model_name, base_model, job_id, dataset_size, accuracy, cost)
get_model_version(model_name, version=None)  # None = latest
list_model_versions(model_name)
set_model_status(model_name, status, version=None)
rollback_model(model_name, target_version)
get_deployment_status()  # Currently deployed models
get_cost_summary(model_name=None)
export_registry(filepath)
```

**Example Registry Entry:**
```json
{
  "my-model": [
    {
      "version": 1,
      "model_name": "my-model",
      "base_model": "gpt-3.5-turbo",
      "job_id": "ftjob-123",
      "dataset_size": 500,
      "accuracy": 0.92,
      "cost": 50.0,
      "status": "ARCHIVED",
      "registered_at": "2024-02-25T10:00:00Z",
      "deployed_at": null
    },
    {
      "version": 2,
      "model_name": "my-model",
      "base_model": "gpt-3.5-turbo",
      "job_id": "ftjob-124",
      "dataset_size": 600,
      "accuracy": 0.95,
      "cost": 55.0,
      "status": "DEPLOYED",
      "registered_at": "2024-02-25T11:00:00Z",
      "deployed_at": "2024-02-25T12:00:00Z"
    }
  ]
}
```

### 7. **Cost Tracker** (`src/fine_tuning/cost_tracker.py`)
Tracks training and inference costs, calculates ROI.

**Cost Tracking:**
- Training cost per job (by dataset size, tokens)
- Inference cost per call (tracked in production)
- Cumulative costs by model
- Break-even analysis

**ROI Calculation:**
- Training cost
- Inference cost reduction
- Accuracy improvement value (default $10 per error saved)
- Payback period in days

**Key Methods:**
```python
record_training_job(job_id, model_name, base_model, dataset_size, training_tokens, total_cost)
record_inference(model_name, tokens_used, cost, is_fine_tuned)
get_job_cost(job_id)
get_model_training_cost(model_name)
get_inference_costs(model_name=None)
calculate_roi(model_name, base_model_inference_cost, expected_inference_count)
get_cost_summary()
```

**ROI Example:**
```
Fine-tune gpt-3.5-turbo on 500 examples:
- Training cost: $50
- Base inference: $0.002/call
- Fine-tuned inference: $0.0015/call
- Expected: 10,000 calls

Cost savings: (0.002 - 0.0015) × 10,000 = $50
Accuracy improvement: 85% → 92% = 7%
Value: 0.07 × 10,000 × $10/error = $7,000
Total ROI: $7,000 + $50 - $50 = $7,000
Payback: Immediate
```

### 8. **CLI Tool** (`src/fine_tuning/cli.py`)
Command-line interface for pipeline management.

**Commands:**
```bash
# Dataset preparation
ft-cli prepare-dataset [--format openai|alpaca|jsonl] [--min-rating 4] [--domain <domain>]

# OpenAI fine-tuning
ft-cli create-openai-job <model> <training_file> [--suffix <suffix>] [--validation-file <file>]
ft-cli check-job-status <job_id>

# Ollama fine-tuning
ft-cli create-ollama-script <base_model> <dataset_file> <output_model_name>

# Evaluation and testing
ft-cli evaluate-model <name> <type> <test_file> [--cost <cost>]
ft-cli setup-ab-test <test_id> <model_a> <model_b>

# Model management
ft-cli register-model <name> <base_model> <job_id> <dataset_size> [--accuracy <accuracy>] [--cost <cost>]
ft-cli list-models
ft-cli rollback-model <model_name> <version>

# Reporting
ft-cli cost-summary
ft-cli help
```

**Usage Examples:**
```bash
# 1. Prepare training dataset
ft-cli prepare-dataset --format openai --min-rating 4 --domain "data_analysis"

# 2. Create OpenAI fine-tuning job
ft-cli create-openai-job gpt-3.5-turbo dataset.jsonl --suffix "v1"

# 3. Check job status
ft-cli check-job-status ftjob-abc123

# 4. Register fine-tuned model
ft-cli register-model my-model gpt-3.5-turbo ftjob-abc123 500 \
  --accuracy 0.95 --cost 50.0

# 5. Evaluate model on test set
ft-cli evaluate-model my-model fine_tuned test_results.jsonl --cost 0.0015

# 6. Setup A/B test
ft-cli setup-ab-test test_001 base-gpt35 finetuned-gpt35

# 7. View all models and deployments
ft-cli list-models

# 8. View cost analysis
ft-cli cost-summary

# 9. Rollback to previous version if needed
ft-cli rollback-model my-model 1
```

## Dataset Preparation

### Data Sources
- **Distillation Collector**: Captures successful cloud model outputs
- **Task History**: Completed tasks from database
- **User Feedback**: High-rated outputs from review process

### Dataset Requirements
```
Minimum Examples: 500
Recommended: 1,000+
Optimal: 5,000+

Per Example:
- Prompt: ≥10 characters
- Response: ≥20 characters
- Rating: ≥4/5 (configurable)
```

### Example Dataset (100 examples shown)
```json
[
  {
    "instruction": "Create a visualization showing quarterly sales trends",
    "output": "import matplotlib.pyplot as plt\nimport pandas as pd\n...",
    "input": ""
  },
  {
    "instruction": "Calculate ROI for an investment",
    "output": "ROI = ((End Value - Start Value) / Start Value) × 100",
    "input": ""
  },
  ...
]
```

## Model Support Matrix

### OpenAI Models

| Model | Training | Fine-tuning | Cost/1K input | Cost/1K output |
|-------|----------|-------------|---------------|----------------|
| gpt-3.5-turbo | ✓ | ✓ | $0.003 | $0.006 |
| gpt-4o-mini | ✓ | ✓ | $0.015 | $0.06 |
| gpt-4 | ✗ | ✗ | - | - |
| gpt-4-turbo | ✗ | ✗ | - | - |

### Ollama/Local Models

| Model | Framework | Status | 
|-------|-----------|--------|
| Llama 2 | Unsloth | ✓ Supported |
| Llama 3.0 | Unsloth | ✓ Supported |
| Llama 3.1 | Unsloth | ✓ Supported |
| Mistral | Unsloth | ✓ Supported |
| Custom | Unsloth | ✓ Supported |

## A/B Testing Coverage

### Test Scenarios Covered

1. **Basic Accuracy Comparison**
   - Exact match: String equality
   - Substring match: Partial correctness
   - Multiple models per test

2. **Statistical Significance**
   - Chi-squared test
   - Configurable alpha (default 0.05)
   - 95% confidence level
   - Minimum sample size: 30 per model (recommended 100+)

3. **Multi-Metric Evaluation**
   - Accuracy: Primary metric
   - Latency: Secondary metric
   - Cost: Tertiary metric
   - Weighted winner selection: 60% accuracy, 20% latency, 20% cost

4. **Production A/B Testing**
   - Live traffic splitting
   - Real-time metric collection
   - Automatic winner detection
   - Rollback support

### Test Example

```python
# Setup
ab_test = ABTestFramework()
ab_test.create_test("test_001", "gpt-35-base", "gpt-35-finetuned")

# Record 100 samples per model
for sample in production_samples:
    if sample.model == "gpt-35-base":
        ab_test.record_sample(
            test_id="test_001",
            model="model_a",
            prediction=sample.prediction,
            reference=sample.reference,
            latency_ms=sample.latency,
            cost=sample.cost
        )
    else:
        # Similar for model_b

# Conclude test
result = ab_test.conclude_test("test_001")

# Results
print(f"Model A accuracy: {result.model_a_accuracy:.2%}")
print(f"Model B accuracy: {result.model_b_accuracy:.2%}")
print(f"Significant: {result.statistical_significance}")
print(f"Winner: {ab_test.recommend_winner(result)}")
```

## Cost Analysis

### Fine-Tuning Costs (Typical)

**Small Dataset (100 examples)**
- OpenAI gpt-3.5-turbo: $3-5
- OpenAI gpt-4o-mini: $15-20
- Local Ollama: Free (compute time only)

**Medium Dataset (500 examples)**
- OpenAI gpt-3.5-turbo: $30-50
- OpenAI gpt-4o-mini: $75-100
- Local Ollama: Free (compute time ~2-4 hours on A100)

**Large Dataset (5,000 examples)**
- OpenAI gpt-3.5-turbo: $300-500
- OpenAI gpt-4o-mini: $750-1,000
- Local Ollama: Free (compute time ~20-40 hours on A100)

### Inference Cost Comparison

**Base Model (gpt-3.5-turbo)**
- Per call: $0.001-0.002 (average)
- 10,000 calls/month: $10-20

**Fine-tuned Model (gpt-3.5-turbo)**
- Per call: $0.0012-0.0018 (similar pricing)
- 10,000 calls/month: $12-18

**Local Model (Ollama)**
- Per call: ~$0 (hardware cost only)
- 10,000 calls/month: Free (amortized hardware)

### ROI Analysis

**Scenario: Fine-tune gpt-3.5-turbo for data analysis**

| Metric | Value |
|--------|-------|
| Dataset size | 500 examples |
| Training cost | $40 |
| Training time | 5 minutes |
| Base model accuracy | 85% |
| Fine-tuned accuracy | 92% |
| Accuracy improvement | +7% |
| Expected calls/month | 5,000 |
| Base cost/call | $0.0015 |
| Fine-tuned cost/call | $0.0015 |
| Cost savings (latency) | $0/month |
| Error reduction value | 5,000 × 0.07 × $10 = $3,500/month |
| **Break-even** | <1 day |
| **6-month ROI** | $21,000 - $40 = $20,960 |
| **ROI%** | 52,400% |

## Test Results

All 35 tests passing:

### Dataset Builder Tests (9 tests)
- ✓ Example validation (valid/invalid)
- ✓ Format conversion (OpenAI, Alpaca, JSONL)
- ✓ Train/test splitting
- ✓ Dataset saving
- ✓ Statistics calculation

### Model Evaluator Tests (6 tests)
- ✓ Exact match evaluation
- ✓ Substring match evaluation
- ✓ Model comparison
- ✓ ROI calculation
- ✓ Results summary

### A/B Testing Tests (6 tests)
- ✓ Test creation and sample recording
- ✓ Test conclusion and analysis
- ✓ Statistical significance testing (chi-squared)
- ✓ Winner recommendation

### Model Registry Tests (7 tests)
- ✓ Model registration with versioning
- ✓ Version management
- ✓ Status updates and deployment
- ✓ Model rollback
- ✓ Cost tracking

### Cost Tracker Tests (5 tests)
- ✓ Training cost recording
- ✓ Inference cost tracking
- ✓ ROI calculation
- ✓ Cost summaries

### Integration Tests (2 tests)
- ✓ Full pipeline end-to-end
- ✓ Model improvement scenarios

**Run Command:**
```bash
pytest tests/test_fine_tuning.py -v
# 35 passed in 0.51s
```

## Integration with Existing Systems

### Distillation Data Collector
Fine-tuning pipeline integrates with existing distillation system:
- Reads from `src/distillation/data_collector.py`
- Uses curated examples (rating ≥4)
- Filters by domain and task type

### LLM Service
Works with existing `src/llm_service.py`:
- Registers fine-tuned models in model config
- Supports task-based model routing
- Fallback mechanism unchanged

### API Models
Adds new models to `src/api/models.py`:
- `FinetuneJobRecord` for tracking
- `ModelDeployment` status tracking
- Cost and performance metrics

## Implementation Details

### File Structure
```
src/fine_tuning/
├── __init__.py                 # Module exports
├── dataset_builder.py          # Dataset preparation
├── openai_fine_tuner.py        # OpenAI integration
├── ollama_fine_tuner.py        # Local fine-tuning
├── model_evaluator.py          # Evaluation metrics
├── ab_testing.py               # A/B testing framework
├── model_registry.py           # Version management
├── cost_tracker.py             # Cost analysis
└── cli.py                      # CLI tool

tests/
└── test_fine_tuning.py         # Comprehensive tests (35 tests)

data/fine_tuning/
├── model_registry.json         # Model versions
├── cost_tracking.json          # Cost records
└── datasets/                   # Training datasets
```

### Data Storage
- **Model Registry**: JSON file with versioned entries
- **Cost Tracking**: JSON file with training and inference records
- **Datasets**: JSONL or JSON files in various formats
- **Logs**: Rotating file logs in `logs/` directory

### Configuration
Environment variables:
```bash
OPENAI_API_KEY=sk-xxx  # Required for OpenAI fine-tuning
OLLAMA_URL=http://localhost:11434  # For local inference
```

## Key Features Summary

| Feature | Status | Details |
|---------|--------|---------|
| Dataset preparation | ✓ Complete | Multiple formats, quality filtering |
| OpenAI API support | ✓ Complete | gpt-3.5-turbo, gpt-4o-mini |
| Local Ollama support | ✓ Complete | Unsloth framework, script generation |
| Model evaluation | ✓ Complete | Accuracy, latency, cost metrics |
| A/B testing | ✓ Complete | Statistical significance, winner selection |
| Model versioning | ✓ Complete | Rollback, deployment tracking |
| Cost tracking | ✓ Complete | ROI, break-even, payback period |
| CLI tool | ✓ Complete | 12+ commands for all operations |
| Test coverage | ✓ Complete | 35 tests, 100% pass rate |

## Future Enhancements

1. **Scheduled Retraining**
   - Cron job to retrain monthly on new data
   - Automatic version management

2. **Advanced Evaluation**
   - BLEU/ROUGE scores for generation tasks
   - Token accuracy for structured output
   - Task-specific metrics

3. **Multi-GPU Training**
   - Distributed training for large datasets
   - Gradient accumulation optimization

4. **Model Compression**
   - Quantization support
   - Model distillation to smaller models

5. **Web Dashboard**
   - Real-time cost tracking
   - A/B test visualization
   - Model performance trends

## Conclusion

Issue #44 delivers a production-ready fine-tuning pipeline with:
- **9 pipeline components** for end-to-end fine-tuning
- **2 backend platforms** (OpenAI + Ollama local)
- **35 comprehensive tests** (100% passing)
- **Full cost tracking** with ROI analysis
- **Statistical A/B testing** for production deployment
- **Model versioning** with rollback capability
- **CLI tool** for easy management

The pipeline is ready for immediate deployment and scaling.
