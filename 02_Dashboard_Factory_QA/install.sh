#!/bin/bash

################################################################################
# Dashboard Factory Tool - Automatic Setup Script
# Platform: macOS and Linux
# 
# This script will:
# 1. Create a Python virtual environment
# 2. Install all required dependencies
# 3. Verify the installation
# 4. Provide next steps
################################################################################

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project directories
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TABLEAU_APP_DIR="$PROJECT_ROOT/Tableau QA Compliance "
VENV_DIR="$PROJECT_ROOT/.venv"
REQUIREMENTS_FILE="$PROJECT_ROOT/requirements.txt"

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Dashboard Factory Tool - Installation Script              ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check Python version
echo -e "${YELLOW}[1/5]${NC} Checking Python version..."
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python3 is not installed${NC}"
    echo "Please install Python 3.9 or higher from https://www.python.org"
    exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "${GREEN}✓ Python $PYTHON_VERSION found${NC}"

# Extract major and minor version
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

# Check if version is 3.9+
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
    echo -e "${RED}✗ Python 3.9 or higher required (found $PYTHON_VERSION)${NC}"
    exit 1
fi

# Check if project directory exists
echo -e "${YELLOW}[2/5]${NC} Validating project structure..."
if [ ! -d "$TABLEAU_APP_DIR" ]; then
    echo -e "${RED}✗ Tableau QA Compliance directory not found${NC}"
    exit 1
fi

if [ ! -f "$REQUIREMENTS_FILE" ]; then
    echo -e "${RED}✗ requirements.txt not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Project structure validated${NC}"

# Create virtual environment
echo -e "${YELLOW}[3/5]${NC} Creating Python virtual environment..."
if [ -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}✓ Virtual environment already exists, using existing${NC}"
else
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Upgrade pip
echo -e "${YELLOW}[4/5]${NC} Installing dependencies..."
pip install --upgrade pip setuptools wheel > /dev/null 2>&1

# Install requirements
pip install -r "$REQUIREMENTS_FILE"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ All dependencies installed successfully${NC}"
else
    echo -e "${RED}✗ Failed to install dependencies${NC}"
    exit 1
fi

# Verification
echo -e "${YELLOW}[5/5]${NC} Verifying installation..."
python3 -c "
import flask
import flask_cors
import pandas
import selenium
import openpyxl
import pptx
print('All core packages verified!')
" 2>/dev/null && echo -e "${GREEN}✓ Installation verified${NC}" || {
    echo -e "${RED}✗ Verification failed${NC}"
    exit 1
}

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║              ✓ Installation Complete!                          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}Next Steps:${NC}"
echo ""
echo "1. ${YELLOW}Activate the virtual environment:${NC}"
echo "   source \"$VENV_DIR/bin/activate\""
echo ""
echo "2. ${YELLOW}Start the Dashboard Factory Tool:${NC}"
echo "   cd \"$TABLEAU_APP_DIR\""
echo "   python3 app.py"
echo ""
echo "3. ${YELLOW}Open in your browser:${NC}"
echo "   http://localhost:5555"
echo ""
echo -e "${YELLOW}For documentation, see:${NC}"
echo "   - USER_GUIDE.md"
echo "   - INSTALLATION_GUIDE.md"
echo "   - API_REFERENCE.md"
echo ""
