#!/bin/bash

# OpenCode Monitor Installation Script
# This script automates the installation process for OpenCode Monitor

set -e  # Exit on any error

echo "🚀 OpenCode Monitor Installation Script"
echo "======================================"

# Check if we're in the right directory
if [ ! -f "setup.py" ] || [ ! -d "ocmonitor" ]; then
    echo "❌ Error: Please run this script from the ocmonitor root directory"
    echo "   The directory should contain setup.py and ocmonitor/ folder"
    exit 1
fi

echo "✅ Found ocmonitor project directory"

# Check Python version
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ "$(printf '%s\n' "3.8" "$PYTHON_VERSION" | sort -V | head -n1)" == "3.8" ]]; then
    echo "✅ Python version $PYTHON_VERSION is supported"
else
    echo "❌ Python 3.8 or higher is required"
    exit 1
fi

# Create virtual environment if it doesn't exist
VENV_DIR="venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "🔨 Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "✅ Virtual environment created"
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Install dependencies
echo "📥 Installing dependencies..."
pip install -r requirements.txt

# Install package in development mode
echo "🔧 Installing ocmonitor in development mode..."
pip install -e .

# Get the scripts directory
SCRIPTS_DIR="$(pwd)/$VENV_DIR/bin"
echo "📁 Python scripts installed to: $SCRIPTS_DIR"

# Test installation
echo "🧪 Testing installation..."
if [ -f "$SCRIPTS_DIR/ocmonitor" ]; then
    echo "✅ ocmonitor command is available in venv"
    "$SCRIPTS_DIR/ocmonitor" --version
else
    echo "⚠️  ocmonitor command not found"
    exit 1
fi

# Install global wrapper
echo ""
echo "🌍 Installing global wrapper..."
PROJECT_DIR="$(pwd)"

# Create the wrapper script content dynamically
cat > ocmonitor-wrapper.sh << 'EOF'
#!/bin/bash
# OpenCode Monitor Global Wrapper Script
# This script allows ocmonitor to be run from anywhere without activating the virtual environment

# Get the directory where this script is located (the project directory)
PROJECT_DIR="PROJECT_DIR_PLACEHOLDER"

# Path to the virtual environment's ocmonitor
OCMONITOR_SCRIPT="$PROJECT_DIR/venv/bin/ocmonitor"

# Check if ocmonitor exists
if [ ! -f "$OCMONITOR_SCRIPT" ]; then
    echo "Error: ocmonitor not found at $OCMONITOR_SCRIPT"
    echo "Please run install.sh from the project directory"
    exit 1
fi

# Execute ocmonitor with all arguments passed to this script
exec "$OCMONITOR_SCRIPT" "$@"
EOF

# Replace placeholder with actual project directory
sed "s|PROJECT_DIR_PLACEHOLDER|$PROJECT_DIR|g" ocmonitor-wrapper.sh > ocmonitor-wrapper.sh.tmp
mv ocmonitor-wrapper.sh.tmp ocmonitor-wrapper.sh

chmod +x ocmonitor-wrapper.sh

# Try to install to user's local bin first (no sudo needed)
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"

if cp ocmonitor-wrapper.sh "$LOCAL_BIN/ocmonitor" 2>/dev/null; then
    echo "✅ Global command installed to $LOCAL_BIN/ocmonitor"
    GLOBAL_INSTALL=true
    
    # Check if LOCAL_BIN is in PATH
    if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
        echo ""
        echo "⚠️  Warning: $LOCAL_BIN is not in your PATH"
        echo ""
        echo "📝 Add this to your shell config file (~/.bashrc or ~/.zshrc):"
        echo "   export PATH=\"$LOCAL_BIN:\$PATH\""
        echo ""
        echo "   Then run: source ~/.bashrc  (or source ~/.zshrc)"
    fi
else
    # Fallback to /usr/local/bin with sudo
    INSTALL_DIR="/usr/local/bin"
    echo "🔐 Installing to $INSTALL_DIR requires sudo privileges..."
    if sudo cp ocmonitor-wrapper.sh "$INSTALL_DIR/ocmonitor" 2>/dev/null; then
        echo "✅ Global command installed to $INSTALL_DIR/ocmonitor"
        GLOBAL_INSTALL=true
    else
        echo "⚠️  Could not install globally"
        echo "   You can manually copy the wrapper:"
        echo "   cp ocmonitor-wrapper.sh ~/.local/bin/ocmonitor"
        echo "   or"
        echo "   sudo cp ocmonitor-wrapper.sh /usr/local/bin/ocmonitor"
        GLOBAL_INSTALL=false
    fi
fi

echo ""
echo "🎉 Installation complete!"
echo ""

if [ "$GLOBAL_INSTALL" = true ]; then
    echo "✅ You can now run 'ocmonitor' from anywhere!"
    echo ""
    echo "📝 Try these commands:"
    echo "   ocmonitor --help"
    echo "   ocmonitor config show"
    echo "   ocmonitor --version"
else
    echo "📝 To use ocmonitor globally, run one of these:"
    echo "   cp ocmonitor-wrapper.sh ~/.local/bin/ocmonitor"
    echo "   (make sure ~/.local/bin is in your PATH)"
    echo ""
    echo "   Or activate the virtual environment:"
    echo "   source $VENV_DIR/bin/activate"
    echo "   ocmonitor --help"
fi

echo ""
echo "For more detailed usage instructions, see MANUAL_TEST_GUIDE.md"