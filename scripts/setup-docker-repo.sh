#!/bin/bash
# Script to add Docker repository and update Docker on Fedora/Nobara (dnf5)

set -e

echo "=== Adding Docker Repository ==="

# Using dnf5 config-manager with --overwrite to handle existing repo
sudo dnf5 config-manager addrepo --overwrite --from-repofile=https://download.docker.com/linux/fedora/docker-ce.repo

echo "=== Docker Repository Added Successfully ==="

echo "=== Removing Conflicting Docker Packages ==="
sudo dnf5 remove -y moby-engine docker-cli docker-compose 2>/dev/null || true

echo "=== Installing Docker CE Packages ==="
sudo dnf5 install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "=== Restarting Docker Service ==="
sudo systemctl restart docker

echo "=== Verifying Docker Version ==="
docker --version

echo "=== Setup Complete ==="
