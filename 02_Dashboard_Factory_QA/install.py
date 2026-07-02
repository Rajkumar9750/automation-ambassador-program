#!/usr/bin/env python3
"""
Dashboard Factory Tool - Universal Installation Script
Works on macOS, Linux, and Windows

Usage:
    python3 install.py
    
Or from the command line:
    python install.py
"""

import os
import sys
import platform
import subprocess
import venv
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output"""
    BLUE = '\033[0;34m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    RED = '\033[0;31m'
    NC = '\033[0m'  # No Color
    
    # Windows safe version
    if platform.system() == 'Windows':
        BLUE = GREEN = YELLOW = RED = NC = ''


def print_header():
    """Print installation header"""
    print(f"{Colors.BLUE}{'='*70}")
    print(f"     Dashboard Factory Tool - Installation Script")
    print(f"{'='*70}{Colors.NC}\n")


def print_step(step_num, total, message):
    """Print step message"""
    print(f"{Colors.YELLOW}[{step_num}/{total}]{Colors.NC} {message}")


def print_success(message):
    """Print success message"""
    print(f"{Colors.GREEN}✓ {message}{Colors.NC}")


def print_error(message):
    """Print error message"""
    print(f"{Colors.RED}✗ {message}{Colors.NC}")
    sys.exit(1)


def check_python_version():
    """Verify Python 3.9+ is installed"""
    print_step(1, 5, "Checking Python version...")
    
    version_info = sys.version_info
    version_str = f"{version_info.major}.{version_info.minor}.{version_info.micro}"
    
    if version_info.major < 3 or (version_info.major == 3 and version_info.minor < 9):
        print_error(f"Python 3.9+ required (found {version_str})")
    
    print_success(f"Python {version_str} detected")


def validate_project_structure():
    """Validate project directory structure"""
    print_step(2, 5, "Validating project structure...")
    
    project_root = Path(__file__).parent
    requirements_file = project_root / "requirements.txt"
    tableau_dir = project_root / "Tableau QA Compliance "
    
    if not requirements_file.exists():
        print_error(f"requirements.txt not found at {requirements_file}")
    
    if not tableau_dir.exists():
        print(f"{Colors.YELLOW}⚠ Warning: Tableau QA Compliance directory not found{Colors.NC}")
    
    print_success("Project structure validated")
    return project_root, requirements_file


def create_virtual_environment(project_root):
    """Create Python virtual environment"""
    print_step(3, 5, "Creating Python virtual environment...")
    
    venv_dir = project_root / ".venv"
    
    if venv_dir.exists():
        print_success("Virtual environment already exists, using existing")
    else:
        try:
            venv.create(str(venv_dir), with_pip=True)
            print_success("Virtual environment created")
        except Exception as e:
            print_error(f"Failed to create virtual environment: {e}")
    
    return venv_dir


def get_pip_executable(venv_dir):
    """Get the pip executable path for the venv"""
    if platform.system() == 'Windows':
        return venv_dir / "Scripts" / "pip.exe"
    else:
        return venv_dir / "bin" / "pip"


def get_python_executable(venv_dir):
    """Get the python executable path for the venv"""
    if platform.system() == 'Windows':
        return venv_dir / "Scripts" / "python.exe"
    else:
        return venv_dir / "bin" / "python"


def install_dependencies(project_root, venv_dir):
    """Install all dependencies from requirements.txt"""
    print_step(4, 5, "Installing dependencies...")
    
    pip_exe = get_pip_executable(venv_dir)
    requirements_file = project_root / "requirements.txt"
    
    try:
        # Upgrade pip, setuptools, and wheel
        print("  • Upgrading pip, setuptools, and wheel...")
        subprocess.run(
            [str(pip_exe), "install", "--upgrade", "pip", "setuptools", "wheel"],
            check=True,
            capture_output=True,
            text=True
        )
        
        # Install requirements
        print("  • Installing packages from requirements.txt...")
        result = subprocess.run(
            [str(pip_exe), "install", "-r", str(requirements_file)],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print_error(f"Failed to install dependencies:\n{result.stderr}")
        
        print_success("All dependencies installed successfully")
    except Exception as e:
        print_error(f"Installation failed: {e}")


def verify_installation(venv_dir):
    """Verify that all core packages are installed"""
    print_step(5, 5, "Verifying installation...")
    
    python_exe = get_python_executable(venv_dir)
    
    verify_code = """
import sys
packages = ['flask', 'flask_cors', 'pandas', 'selenium', 'openpyxl', 'pptx']
missing = []
for pkg in packages:
    try:
        __import__(pkg)
    except ImportError:
        missing.append(pkg)

if missing:
    print(f"Missing packages: {', '.join(missing)}")
    sys.exit(1)
else:
    print("All core packages verified!")
"""
    
    try:
        result = subprocess.run(
            [str(python_exe), "-c", verify_code],
            capture_output=True,
            text=True,
            check=True
        )
        print_success("Installation verified")
    except subprocess.CalledProcessError:
        print_error("Verification failed - some packages missing")


def print_next_steps(venv_dir):
    """Print instructions for next steps"""
    print(f"\n{Colors.BLUE}{'='*70}")
    print(f"              ✓ Installation Complete!")
    print(f"{'='*70}{Colors.NC}\n")
    
    print(f"{Colors.GREEN}Next Steps:{Colors.NC}\n")
    
    if platform.system() == 'Windows':
        activate_cmd = ".venv\\Scripts\\activate.bat"
        run_cmd = "python app.py"
    else:
        activate_cmd = "source .venv/bin/activate"
        run_cmd = "python3 app.py"
    
    print(f"1. {Colors.YELLOW}Activate the virtual environment:{Colors.NC}")
    print(f"   {activate_cmd}\n")
    
    print(f"2. {Colors.YELLOW}Navigate to the app directory:{Colors.NC}")
    print(f'   cd "Tableau QA Compliance "\n')
    
    print(f"3. {Colors.YELLOW}Start the Dashboard Factory Tool:{Colors.NC}")
    print(f"   {run_cmd}\n")
    
    print(f"4. {Colors.YELLOW}Open in your browser:{Colors.NC}")
    print(f"   http://localhost:5555\n")
    
    print(f"{Colors.YELLOW}For documentation, see:{Colors.NC}")
    print(f"   • USER_GUIDE.md")
    print(f"   • INSTALLATION_GUIDE.md")
    print(f"   • API_REFERENCE.md")
    print(f"   • ROLLOUT_PLAN.md\n")


def main():
    """Main installation function"""
    try:
        print_header()
        
        # Step 1: Check Python version
        check_python_version()
        
        # Step 2: Validate project structure
        project_root, requirements_file = validate_project_structure()
        
        # Step 3: Create virtual environment
        venv_dir = create_virtual_environment(project_root)
        
        # Step 4: Install dependencies
        install_dependencies(project_root, venv_dir)
        
        # Step 5: Verify installation
        verify_installation(venv_dir)
        
        # Print next steps
        print_next_steps(venv_dir)
        
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Installation cancelled by user{Colors.NC}")
        sys.exit(1)
    except Exception as e:
        print_error(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
