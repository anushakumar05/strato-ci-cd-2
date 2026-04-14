# src/config.py
import os
from pathlib import Path

# Project root is the parent of src/
_project_root = Path(__file__).resolve().parent.parent

# ============================================================================
# Environment Loading
# ============================================================================
# Try multiple sources: .env, env.conf, config.env (macOS sandbox may block
# reading hidden dot-files, so we also try non-hidden alternatives).

def _load_env_file(filepath):
    """
    Manually parse a .env-style file and set environment variables.
    Handles macOS sandbox PermissionError gracefully.
    """
    try:
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    os.environ[key] = value
        return True
    except (PermissionError, FileNotFoundError, OSError):
        return False


def _load_environment():
    """Try to load env vars from multiple sources."""
    # 1. Try python-dotenv with the standard .env
    try:
        from dotenv import load_dotenv
        if load_dotenv(_project_root / ".env", override=True):
            return
    except (ImportError, PermissionError, OSError):
        pass

    # 2. Try manual parser on .env
    if _load_env_file(_project_root / ".env"):
        return

    # 3. Try non-hidden alternatives (sandbox workaround)
    for alt_name in ["env.conf", "config.env", "env.txt"]:
        if _load_env_file(_project_root / alt_name):
            return

    # 4. Try Streamlit secrets (works when running under Streamlit)
    try:
        import streamlit as st
        if hasattr(st, "secrets") and len(st.secrets) > 0:
            for key in st.secrets:
                os.environ[key] = str(st.secrets[key])
            return
    except Exception:
        pass


_load_environment()


# ============================================================================
# GEMINI API Keys
# ============================================================================
# Load multiple keys from a comma-separated string
_keys_env = os.getenv("GEMINI_API_KEYS")
if _keys_env:
    _keys_env = _keys_env.strip(' "\'')
    GEMINI_API_KEYS = [k.strip(' "\'') for k in _keys_env.split(",") if k.strip(' "\'')]
else:
    # Fallback if someone uses the old variable name
    single_key = os.getenv("GEMINI_API_KEY")
    GEMINI_API_KEYS = [single_key.strip(' "\'')] if single_key else []

# Keep this for backward compatibility (points to the first key initially)
GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else None


# ============================================================================
# GitHub Configuration
# ============================================================================
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_OWNER")
GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")


# ============================================================================
# Validation
# ============================================================================
missing = []
for var, val in {
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "GITHUB_TOKEN": GITHUB_TOKEN,
    "GITHUB_OWNER": GITHUB_OWNER,
    "GITHUB_REPO": GITHUB_REPO,
}.items():
    if not val:
        missing.append(var)
if missing:
    print(f"Warning: missing environment variables: {', '.join(missing)}")
    print(f"  Tip: If .env is blocked by sandbox, copy it to 'env.conf':")
    print(f"    cp .env env.conf")


# ============================================================================
# Project Paths
# ============================================================================
PROJECT_ROOT = Path(__file__).resolve().parent
GENERATED_DIR = PROJECT_ROOT / "generated"
CODE_SUMMARY_PATH = PROJECT_ROOT / "generated" / "README.md"