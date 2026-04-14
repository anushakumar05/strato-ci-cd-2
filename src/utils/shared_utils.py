# src/utils/shared_utils.py
"""
Shared Utilities - Eliminates code duplication across modules

Contains common patterns used throughout the codebase:
- JSON parsing from LLM responses
- Path handling
- Error handling wrappers
- Common validations
"""

import re
import json
from typing import Dict, Any, Optional, Tuple, Callable
from pathlib import Path


# ============================================================================
# JSON Parsing Utilities
# ============================================================================

def extract_json_from_response(response: str, default: dict = None) -> dict:
    """
    Extract JSON from LLM response (handles markdown fences)
    
    Args:
        response: Raw LLM response
        default: Default dict if parsing fails
        
    Returns:
        Parsed JSON dict or default
    """
    try:
        # Remove markdown fences if present
        cleaned = response.strip()
        if '```json' in cleaned:
            cleaned = re.sub(r'```json\s*', '', cleaned)
            cleaned = re.sub(r'```\s*$', '', cleaned)
        elif '```' in cleaned:
            cleaned = re.sub(r'```\s*', '', cleaned)
        
        # Extract first JSON object
        json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        
        return default or {}
    
    except json.JSONDecodeError as e:
        print(f"⚠️  JSON parse error: {e}")
        return default or {}
    except Exception as e:
        print(f"⚠️  Unexpected error parsing JSON: {e}")
        return default or {}


def create_empty_plan() -> dict:
    """Create an empty plan structure (used as default)"""
    return {
        "summary": "Could not parse plan",
        "files_to_create": [],
        "files_to_edit": [],
        "files_to_delete": [],
        "implementation_order": []
    }


# ============================================================================
# Path Utilities
# ============================================================================

def sanitize_filepath(filepath: str) -> str:
    """
    Sanitize filepath to prevent directory traversal
    
    Args:
        filepath: User-provided filepath
        
    Returns:
        Sanitized filepath
    """
    # Remove directory traversal patterns
    clean = filepath.replace("../", "").replace("..\\", "")
    
    # Remove leading slashes
    clean = clean.lstrip("/").lstrip("\\")
    
    # Ensure .py extension for Python files
    if not clean.endswith('.py') and '.' not in Path(clean).name:
        clean += '.py'
    
    return clean


def split_path_and_filename(filepath: str) -> Tuple[str, str]:
    """
    Split filepath into directory and filename
    
    Args:
        filepath: Full filepath
        
    Returns:
        Tuple of (directory, filename)
    """
    path = Path(filepath)
    return str(path.parent), path.name


# ============================================================================
# Error Handling Wrappers
# ============================================================================

def safe_execute(func: Callable, *args, error_message: str = "Operation failed", 
                default_return: Any = None, **kwargs) -> Any:
    """
    Safely execute a function with error handling
    
    Args:
        func: Function to execute
        *args: Positional arguments
        error_message: Message to show on error
        default_return: Value to return on error
        **kwargs: Keyword arguments
        
    Returns:
        Function result or default_return on error
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"❌ {error_message}: {e}")
        return default_return


def validate_github_config(owner: str, repo: str, branch: str) -> bool:
    """
    Validate GitHub configuration
    
    Args:
        owner: GitHub owner
        repo: Repository name
        branch: Branch name
        
    Returns:
        True if valid, False otherwise
    """
    if not all([owner, repo, branch]):
        missing = []
        if not owner:
            missing.append("GITHUB_OWNER")
        if not repo:
            missing.append("GITHUB_REPO")
        if not branch:
            missing.append("GITHUB_BRANCH")
        
        print(f"❌ Missing GitHub config: {', '.join(missing)}")
        return False
    
    return True


# ============================================================================
# String Utilities
# ============================================================================

def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate string to max length
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add when truncated
        
    Returns:
        Truncated string
    """
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted string (e.g., "1.2 KB")
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


# ============================================================================
# Validation Utilities
# ============================================================================

def is_valid_python_identifier(name: str) -> bool:
    """Check if string is valid Python identifier"""
    if not name:
        return False
    return name.isidentifier()


def is_safe_code_pattern(code: str) -> Tuple[bool, list]:
    """
    Quick check for dangerous code patterns
    
    Args:
        code: Code to check
        
    Returns:
        Tuple of (is_safe, list_of_warnings)
    """
    warnings = []
    
    # Critical patterns
    if "eval(" in code:
        warnings.append("CRITICAL: eval() detected")
    if "exec(" in code:
        warnings.append("CRITICAL: exec() detected")
    if "__import__" in code:
        warnings.append("WARNING: Dynamic imports detected")
    
    # Secret patterns
    secret_pattern = r'(api[_-]?key|password|secret|token)\s*=\s*["\'][^"\']{10,}["\']'
    if re.search(secret_pattern, code, re.IGNORECASE):
        warnings.append("CRITICAL: Hardcoded credentials detected")
    
    is_safe = not any('CRITICAL' in w for w in warnings)
    return is_safe, warnings


# ============================================================================
# Dictionary Utilities
# ============================================================================

def merge_dicts(*dicts: dict) -> dict:
    """
    Merge multiple dictionaries (later dicts override earlier)
    
    Args:
        *dicts: Dictionaries to merge
        
    Returns:
        Merged dictionary
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


def get_nested_value(data: dict, key_path: str, default: Any = None) -> Any:
    """
    Get value from nested dict using dot notation
    
    Args:
        data: Dictionary to search
        key_path: Dot-separated path (e.g., "user.profile.name")
        default: Default value if not found
        
    Returns:
        Value at path or default
    
    Example:
        >>> data = {"user": {"profile": {"name": "Alice"}}}
        >>> get_nested_value(data, "user.profile.name")
        'Alice'
    """
    keys = key_path.split('.')
    value = data
    
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    
    return value


# ============================================================================
# Common Patterns
# ============================================================================

class ResultStatus:
    """Standard result status codes"""
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    PARTIAL = "partial"


def create_result(status: str, message: str, data: dict = None) -> dict:
    """
    Create standardized result dictionary
    
    Args:
        status: Status code (use ResultStatus constants)
        message: Human-readable message
        data: Optional additional data
        
    Returns:
        Standardized result dict
    """
    result = {
        "status": status,
        "message": message
    }
    
    if data:
        result["data"] = data
    
    return result


def retry_with_backoff(func: Callable, max_retries: int = 3, 
                      base_delay: float = 1.0, **kwargs) -> Any:
    """
    Retry function with exponential backoff
    
    Args:
        func: Function to retry
        max_retries: Maximum retry attempts
        base_delay: Base delay in seconds
        **kwargs: Arguments to pass to func
        
    Returns:
        Function result
        
    Raises:
        Last exception if all retries fail
    """
    import time
    
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func(**kwargs)
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                print(f"⚠️  Retry {attempt + 1}/{max_retries} after {delay}s...")
                time.sleep(delay)
    
    raise last_exception


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # JSON
    'extract_json_from_response',
    'create_empty_plan',
    
    # Paths
    'sanitize_filepath',
    'split_path_and_filename',
    
    # Error handling
    'safe_execute',
    'validate_github_config',
    'retry_with_backoff',
    
    # Strings
    'truncate_string',
    'format_file_size',
    
    # Validation
    'is_valid_python_identifier',
    'is_safe_code_pattern',
    
    # Dicts
    'merge_dicts',
    'get_nested_value',
    
    # Results
    'ResultStatus',
    'create_result'
]