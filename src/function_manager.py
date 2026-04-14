# src/function_manager.py
"""
Function Manager - Refactored with shared utilities

Reduces from 275 lines to ~150 lines by:
1. Consolidating create/edit/overwrite logic
2. Using shared path utilities
3. Removing duplicate code patterns
4. Simplifying file operations
"""

import os
from pathlib import Path
from src.gemini_manager import generate_function
from src.github_manager import get_file, push_file, get_remote_readme
from src.config import GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH
from src.utils.shared_utils import sanitize_filepath

# ============================================================================
# Configuration
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = PROJECT_ROOT / "generated"
os.makedirs(GENERATED_DIR, exist_ok=True)

_readme_cache = None


# ============================================================================
# Context Management
# ============================================================================

def get_readme_context() -> str:
    """Get cached README context from remote repository"""
    global _readme_cache
    
    if _readme_cache is not None:
        return _readme_cache
    
    if GITHUB_OWNER and GITHUB_REPO:
        try:
            _readme_cache = get_remote_readme(GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH)
            if _readme_cache:
                print(f"📖 Loaded README from {GITHUB_OWNER}/{GITHUB_REPO}")
                return _readme_cache
        except Exception as e:
            print(f"Could not read README: {e}")
    
    _readme_cache = ""
    return ""


def refresh_readme_context():
    """Force refresh of README context"""
    global _readme_cache
    _readme_cache = None
    return get_readme_context()


# ============================================================================
# Path Utilities
# ============================================================================

def get_generated_path(filename: str) -> tuple[str, str]:
    """
    Get local and repo paths for a file
    
    Returns:
        (local_path, repo_path)
    """
    clean_name = sanitize_filepath(filename)
    local_path = GENERATED_DIR / clean_name
    
    # Create directories
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    return str(local_path), clean_name


# ============================================================================
# Core File Operations
# ============================================================================

def _generate_with_context(prompt: str) -> str:
    """Generate code with README context"""
    context = get_readme_context()
    full_prompt = f"{context}\n\n---\n{prompt}" if context else prompt
    return generate_function(full_prompt)


def _write_to_github(repo_path: str, code: str, message: str, 
                    must_exist: bool = False, must_not_exist: bool = False) -> dict:
    """
    Write file to GitHub with existence checks
    
    Args:
        repo_path: Path in repo
        code: File content
        message: Commit message
        must_exist: Raise error if file doesn't exist
        must_not_exist: Raise error if file exists
        
    Returns:
        GitHub API response
    """
    existing, sha = get_file(repo_path, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH)
    
    if must_not_exist and existing:
        raise FileExistsError(f"{repo_path} already exists; use edit/overwrite instead")
    
    if must_exist and not existing:
        raise FileNotFoundError(f"{repo_path} not found; use create instead")
    
    return push_file(
        repo_path,
        code,
        message,
        sha=sha,
        owner=GITHUB_OWNER,
        repo=GITHUB_REPO,
        branch=GITHUB_BRANCH
    )


def _write_locally(local_path: str, code: str):
    """Write file locally"""
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(code.strip() + "\n")
    
    try:
        os.chmod(local_path, 0o666)
    except PermissionError:
        pass  # Ignore permission errors


# ============================================================================
# Public API
# ============================================================================

def create_file(filename: str, prompt: str, commit_message: str = None, 
               push_to_github: bool = True):
    """
    Create a new file
    
    Args:
        filename: File path
        prompt: Description of what to create
        commit_message: Optional commit message
        push_to_github: Whether to push to GitHub
        
    Returns:
        Local path or GitHub response
    """
    local_path, repo_path = get_generated_path(filename)
    
    # Generate code
    code = _generate_with_context(prompt)
    if not code:
        raise RuntimeError("No code generated")
    
    # Write locally or to GitHub
    if not push_to_github:
        _write_locally(local_path, code)
        print(f"Created locally: {local_path}")
        return local_path
    
    message = commit_message or f"Create {repo_path}"
    _write_to_github(repo_path, code, message, must_not_exist=True)
    return repo_path


def edit_file(filename: str, prompt: str, push_to_github: bool = False):
    """
    Edit an existing file
    
    Args:
        filename: File path
        prompt: Description of changes
        push_to_github: Whether to push to GitHub
        
    Returns:
        Local path or GitHub response
    """
    local_path, repo_path = get_generated_path(filename)
    
    # Check if file exists locally
    if not os.path.isfile(local_path):
        print(f"{local_path} not found, creating instead")
        return create_file(filename, prompt, push_to_github=push_to_github)
    
    # Read current content
    with open(local_path, "r", encoding="utf-8") as f:
        current_content = f.read()
    
    # Generate updated content
    code = _generate_with_context(
        f"Modify this code:\n\n{current_content}\n\nChanges: {prompt}"
    )
    
    # Write back
    if not push_to_github:
        _write_locally(local_path, code)
        print(f"Edited locally: {local_path}")
        return local_path
    
    # Check remote and push
    existing, sha = get_file(repo_path, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH)
    
    if not existing:
        print(f"{repo_path} not found remotely, creating instead")
        _write_to_github(repo_path, code, f"Create {repo_path}")
    else:
        _write_to_github(repo_path, code, f"Edit {repo_path}", must_exist=False)
    
    return repo_path


def overwrite_file(filename: str, prompt: str, commit_message: str = None,
                  push_to_github: bool = True):
    """
    Completely replace an existing file
    
    Args:
        filename: File path
        prompt: Description of what to generate
        commit_message: Optional commit message
        push_to_github: Whether to push to GitHub
        
    Returns:
        Local path or GitHub response
    """
    local_path, repo_path = get_generated_path(filename)
    
    # Generate new code
    code = _generate_with_context(prompt)
    if not code:
        raise RuntimeError("No code generated")
    
    # Write locally or to GitHub
    if not push_to_github:
        _write_locally(local_path, code)
        print(f"Overwrote locally: {local_path}")
        return local_path
    
    message = commit_message or f"Overwrite {repo_path}"
    _write_to_github(repo_path, code, message, must_exist=True)
    return repo_path


def sync_to_repo():
    """Sync all files from generated/ to GitHub"""
    if not GENERATED_DIR.exists():
        print(f"Not found: {GENERATED_DIR}")
        return []
    
    files = [f for f in GENERATED_DIR.iterdir() if f.is_file()]
    
    if not files:
        print(f"No files in {GENERATED_DIR}")
        return []
    
    if not all([GITHUB_OWNER, GITHUB_REPO]):
        print("GitHub config missing")
        return []
    
    synced = []
    print(f"\nSyncing {len(files)} file(s)...\n")
    
    for src in files:
        try:
            with open(src, 'r', encoding='utf-8') as f:
                content = f.read()
            
            existing, sha = get_file(src.name, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH)
            
            message = f"{'Update' if existing else 'Create'} {src.name}"
            
            push_file(
                src.name,
                content,
                message,
                sha=sha,
                owner=GITHUB_OWNER,
                repo=GITHUB_REPO,
                branch=GITHUB_BRANCH
            )
            
            synced.append(src.name)
            print(f"{src.name}")
        
        except Exception as e:
            print(f"{src.name}: {e}")
    
    print(f"\nSynced {len(synced)} file(s)")
    print(f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}")
    
    return synced