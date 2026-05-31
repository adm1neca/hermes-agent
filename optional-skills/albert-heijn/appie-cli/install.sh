#!/bin/bash
set -e

echo "🛒 Building appie-cli..."

# Check Go is installed
if ! command -v go &> /dev/null; then
    echo "❌ Go is not installed. Install from https://go.dev/dl/"
    exit 1
fi

cd "$(dirname "$0")"
go build -o appie-cli .

# Try to move to a PATH directory
if [ -d "$HOME/go/bin" ]; then
    mv appie-cli "$HOME/go/bin/"
    echo "✅ Installed to ~/go/bin/appie-cli"
elif [ -d "$HOME/.local/bin" ]; then
    mv appie-cli "$HOME/.local/bin/"
    echo "✅ Installed to ~/.local/bin/appie-cli"
else
    mkdir -p "$HOME/go/bin"
    mv appie-cli "$HOME/go/bin/"
    echo "✅ Installed to ~/go/bin/appie-cli"
    echo "   Add to PATH: export PATH=\$HOME/go/bin:\$PATH"
fi

echo ""
echo "🔐 Next: run 'appie-cli login-url' to authenticate with Albert Heijn"
