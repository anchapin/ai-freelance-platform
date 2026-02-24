#!/bin/bash
# Script to run vLLM with AMD GPU on Nobara Linux using ROCm Docker image

set -e

MODEL=${1:-"Qwen/Qwen3-30B-A3B-Thinking-2507"}
TP=${2:-1}

echo "=== Running vLLM with ROCm Docker image ==="
echo "Model: $MODEL"
echo "Tensor Parallel Size: $TP"

# Note: RX 6600 (gfx1032/RDNA2) needs AITER disabled
# The ROCm vLLM image is optimized for MI series GPUs - consumer GPUs may have issues

docker run -d --network=host \
    --device=/dev/kfd --device=/dev/dri --group-add=video \
    --ipc=host \
    --shm-size 16G \
    -v ~/.cache/huggingface:/root/.cache/huggingface \
    -p 8000:8000 \
    -e VLLM_ROCM_USE_AITER=0 \
    rocm/vllm:latest \
    vllm serve $MODEL \
    --tensor-parallel-size $TP \
    --gpu-memory-utilization 0.9 \
    --enforce-eager \
    --disable-log-requests

echo "=== vLLM Server Starting ==="
echo "API will be available at: http://localhost:8000"
echo "OpenAPI docs at: http://localhost:8000/v1"
echo ""
echo "To check logs: docker logs \$(docker ps -q -l)"
echo "To stop: docker stop \$(docker ps -q -l)"
