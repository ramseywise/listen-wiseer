#!/bin/bash

# listen-wiseer setup script

set -e

echo "Setting up listen-wiseer..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "uv is not installed. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    echo "uv installed successfully"
else
    echo "uv is already installed"
fi

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "Please edit .env and add your API keys before running the app"
else
    echo ".env file already exists"
fi

# Install dependencies
echo "Installing dependencies with uv..."
uv sync

# Create necessary directories
echo "Creating data directories..."
mkdir -p data/listening_history data/cache data/library logs

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. git lfs pull   (fetches infrastructure/db/listen_wiseer.db)"
echo ""
echo "2. Edit .env and fill in:"
echo "   - ANTHROPIC_API_KEY (required), TAVILY_API_KEY"
echo "   - LAST_FM_API_KEY, LISTENBRAINZ_TOKEN / LISTENBRAINZ_USER, YOUTUBE_API_KEY, JAMENDO_CLIENT_ID"
echo ""
echo "3. Optional: uv sync --extra embeddings   (semantic memory search; pulls torch)"
echo ""
echo "4. Train models and check readiness:"
echo "   make train && make doctor"
echo ""
echo "5. Run the app:"
echo "   make app            # or: make infra-build && make infra-up"
echo ""
echo "6. Optional: drop your Spotify privacy-export JSON in data/listening_history/,"
echo "   then: make import-history && make resolve-ids"
echo ""
