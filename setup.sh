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
mkdir -p data/listening_history data/cache data/vectorstore logs

echo ""
echo "Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and fill in:"
echo "   - SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET (https://developer.spotify.com/dashboard)"
echo "   - SPOTIFY_USER_ID"
echo "   - ANTHROPIC_API_KEY (https://console.anthropic.com)"
echo ""
echo "2. Place your Spotify listening history JSON files in data/listening_history/"
echo ""
echo "3. Run the app:"
echo "   uv run chainlit run src/app/main.py"
echo ""
echo "4. Or with Docker:"
echo "   docker compose up"
echo ""
echo "5. Run tests:"
echo "   uv run pytest"
echo ""
