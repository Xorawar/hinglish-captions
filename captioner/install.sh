#!/usr/bin/env zsh

# Exit immediately if any command fails
set -e

echo "=== Starting Captioner CLI Installation ==="

# 1. Create a clean Python virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# 2. Upgrade core packaging tools
echo "Upgrading pip and wheel..."
pip install --upgrade pip wheel setuptools

# 3. Install required architecture-specific packages
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# 4. Create the global symlink for the transcribe command
echo "Setting up global CLI symlink..."
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

# Write wrapper execution script to native local bin
CAT_BIN="$INSTALL_DIR/transcribe"
cat << 'EOF' > "$CAT_BIN"
#!/usr/bin/env zsh
SOURCE_DIR="$HOME/captioner"
source "$SOURCE_DIR/venv/bin/activate"
python3 "$SOURCE_DIR/captioner_cli/transcribe.py" "$@"
EOF

chmod +x "$CAT_BIN"

# 5. Verify PATH accessibility
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo "Warning: $HOME/.local/bin is not in your PATH."
    echo "Please add this line to your ~/.zshrc file:"
    echo 'export PATH="$HOME/.local/bin:$PATH"'
fi

echo "=== Installation Complete! ==="
echo "You can now run the 'transcribe' command globally once your PATH is sourced."

