#!/usr/bin/env python3
"""
Launcher script for Multi-Agent Pipeline Streamlit UI

Usage:
    python launch_ui.py
    python launch_ui.py --port 8502
    python launch_ui.py --help
"""

import sys
import subprocess
import argparse
from pathlib import Path


def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        import streamlit
        print("Streamlit is installed")
        return True
    except ImportError:
        print("Streamlit is not installed")
        print("\nTo install Streamlit, run:")
        print("  pip install streamlit")
        print("\nOr install all UI dependencies:")
        print("  pip install -r requirements-streamlit.txt")
        return False


def check_config():
    """Check if .env file exists"""
    env_file = Path(".env")
    if not env_file.exists():
        print("Warning: .env file not found")
        print("Make sure you have configured:")
        print("  - GEMINI_API_KEY")
        print("  - GITHUB_TOKEN")
        print("  - GITHUB_OWNER")
        print("  - GITHUB_REPO")
        print("  - GITHUB_BRANCH")
        return False
    else:
        print(".env file found")
        return True


def launch_streamlit(port=8501, host="localhost"):
    """Launch Streamlit app"""
    app_file = Path("streamlit_app.py")
    
    if not app_file.exists():
        print(f"Error: {app_file} not found")
        print("Make sure you're in the project root directory")
        sys.exit(1)
    
    print(f"\nLaunching Streamlit UI on http://{host}:{port}")
    print("Press Ctrl+C to stop the server\n")
    
    cmd = [
        "streamlit",
        "run",
        str(app_file),
        f"--server.port={port}",
        f"--server.address={host}"
    ]
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n\nStreamlit server stopped")
    except Exception as e:
        print(f"\nError launching Streamlit: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Launch Multi-Agent Pipeline Streamlit UI"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Port to run the server on (default: 8501)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Host to run the server on (default: localhost)"
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip dependency and config checks"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Multi-Agent Pipeline - Streamlit UI Launcher")
    print("=" * 60)
    print()
    
    if not args.skip_checks:
        # Check dependencies
        if not check_dependencies():
            sys.exit(1)
        
        print()
        
        # Check config
        check_config()
        
        print()
    
    # Launch
    launch_streamlit(port=args.port, host=args.host)


if __name__ == "__main__":
    main()