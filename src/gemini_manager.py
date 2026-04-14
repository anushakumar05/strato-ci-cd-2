# src/gemini_manager.py
import re
import time
import random
from typing import Optional
from src.config import GEMINI_API_KEY, GEMINI_API_KEYS
from src.config import CODE_SUMMARY_PATH
from pathlib import Path
# change
current_key_index = 0

# try to import google.generativeai, but don't break if unavailable
try:
    import google.generativeai as genai
    genai_available = True
except Exception:
    genai_available = False

if genai_available and GEMINI_API_KEYS:
    genai.configure(api_key=GEMINI_API_KEYS[0])
    MODEL_NAME = "gemini-2.5-flash"
else:
    MODEL_NAME = None

def clean_gemini_code(response: str) -> str:
    """
    Clean LLM output and return only Python code.
    - Remove markdown fences and leading explanatory lines.
    - Try to extract the first code block that looks like Python.
    """
    if not response:
        return ""

    text = response.strip()

    # If fenced code blocks exist, extract the content inside the first fence
    if "```" in text:
        # Split on opening fences (```python or ```)
        parts = re.split(r"```(?:python|py)?\s*\n?", text)
        # parts alternates: before_fence, code_block, after_fence, code_block, ...
        # Try to find the best code block (one with Python code)
        best = None
        fallback = None
        for i, part in enumerate(parts):
            # Skip the "before first fence" part (index 0) — that's usually explanation
            if i == 0:
                continue
            # Remove trailing ``` if it's at the end of this part
            candidate = part.strip()
            if candidate.endswith("```"):
                candidate = candidate[:-3].strip()
            candidate = candidate.strip("`\n\r ")
            if not candidate:
                continue
            if fallback is None:
                fallback = candidate
            if ("def " in candidate) or ("import " in candidate) or ("from " in candidate) or ('"""' in candidate) or ("class " in candidate):
                best = candidate
                break

        # Use best match, or fallback to first non-empty block
        result = best or fallback
        if result:
            return result

    # If no fences, try to remove leading lines of explanation
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith(("def ", "import ", "from ", "#", '"""', "class ")):
            start = i
            break
    cleaned = "\n".join(lines[start:]).strip()

    # remove any leading "Here's the code:" style lines
    cleaned = re.sub(r'^\s*(here(\'s| is)|ok,?)[:\s\-]*', '', cleaned, flags=re.I)
    return cleaned


# ============================================================================
# Rate-Limit Callback (for UI integration)
# ============================================================================

_rate_limit_callback = None


def set_rate_limit_callback(callback):
    """
    Register a callback that fires when the API hits a rate limit.
    
    The callback receives: (wait_seconds: float, attempt: int, max_retries: int)
    
    The callback is responsible for sleeping the wait duration (shows countdown).
    If no callback is set, _call_gemini_raw falls back to plain time.sleep.
    
    Usage in Streamlit:
        from src.gemini_manager import set_rate_limit_callback
        set_rate_limit_callback(my_streamlit_countdown_fn)
    
    Set to None to clear:
        set_rate_limit_callback(None)
    """
    global _rate_limit_callback
    _rate_limit_callback = callback


def _wait_with_callback(wait_seconds: float, attempt: int, max_retries: int):
    """
    Sleep for wait_seconds. If a UI callback is registered, delegate to it
    (so it can show a countdown). Otherwise plain time.sleep.
    """
    if _rate_limit_callback:
        try:
            _rate_limit_callback(wait_seconds, attempt, max_retries)
            return  # callback handled the sleep
        except Exception:
            pass  # callback failed, fall through to plain sleep
    time.sleep(wait_seconds)


def _call_gemini_raw(prompt: str, max_retries: int = 5, base_delay: int = 15) -> str:
    """
    Calls Gemini API with exponential backoff and automatic key rotation for rate limits.
    """
    global current_key_index
    
    if not genai_available or not MODEL_NAME:
        raise RuntimeError("google.generativeai not available or GEMINI_API_KEYS missing.")
    
    model = genai.GenerativeModel(MODEL_NAME)
    actual_retries = max(max_retries, len(GEMINI_API_KEYS) * 2) if GEMINI_API_KEYS else max_retries
    
    for attempt in range(actual_retries):
        try:
            resp = model.generate_content(
                prompt,
                request_options={"timeout": 120},  # 2-minute timeout
            )
            if hasattr(resp, "text"):
                return resp.text
            return str(resp)
            
        except Exception as e:
            error_str = str(e).lower()
            
            # 1. Invalid API Key Check (Catches 400 and 403 errors)
            if any(err in error_str for err in ["api key not valid", "api_key_invalid", "project", "denied", "permission", "403"]):
                if len(GEMINI_API_KEYS) > 1:
                    print(f"      [!] Invalid API Key detected at index {current_key_index}. Rotating...")
                    current_key_index = (current_key_index + 1) % len(GEMINI_API_KEYS)
                    genai.configure(api_key=GEMINI_API_KEYS[current_key_index])
                    model = genai.GenerativeModel(MODEL_NAME)
                    continue
                else:
                    raise e

            # 2. Rate Limit / Quota Check (Catches the 429 error)
            if "429" in error_str or "quota" in error_str or "resource exhausted" in error_str:
                if attempt == actual_retries - 1:
                    raise RuntimeError(f"Gemini API Quota exceeded on all available keys.") from e
                
                if len(GEMINI_API_KEYS) > 1:
                    current_key_index = (current_key_index + 1) % len(GEMINI_API_KEYS)
                    print(f"      [!] Rate limit hit. Rotating to API Key {current_key_index + 1}/{len(GEMINI_API_KEYS)}...")
                    
                    genai.configure(api_key=GEMINI_API_KEYS[current_key_index])
                    model = genai.GenerativeModel(MODEL_NAME)
                    
                    if current_key_index == 0:
                        # Cycled through all keys — need to wait
                        wait_time = (base_delay * (2 ** (attempt // len(GEMINI_API_KEYS)))) + random.uniform(1, 3)
                        print(f"      [!] All keys exhausted. Waiting {wait_time:.1f}s before next cycle...")
                        _wait_with_callback(wait_time, attempt + 1, actual_retries)
                    else:
                        time.sleep(0.5)
                else:
                    # Single key — just wait
                    wait_time = (base_delay * (2 ** attempt)) + random.uniform(1, 3)
                    print(f"      [!] Rate limit hit. Waiting {wait_time:.1f}s before retry {attempt + 1}/{actual_retries}...")
                    _wait_with_callback(wait_time, attempt + 1, actual_retries)
            else:
                raise e
    
    return ""


# Builds a request prompt for Gemini; 
    # "Write a Python function according to this request... Returns only Python code"
    # Sends that prompt back to Gemini's API (google.generativeai)
    # Gets back text (could be markdown, explanation, code)
    # Cleans it up using clean_gemini_code() - removes backticks, markdown, etc.
    # Returns only clean python code
def generate_function(prompt: str, system_prompt: Optional[str] = None) -> str:
    """
    Ask Gemini to generate Python code for a function.
    Automatically includes project code summary if available.
    """

    # --- Load summary context automatically ---
    context = ""
    if CODE_SUMMARY_PATH.exists():
        try:
            with open(CODE_SUMMARY_PATH, "r", encoding="utf-8") as f:
                context = f.read()
        except Exception as e:
            print(f"Could not read code summary: {e}")

    # --- Build prompt ---
    full_prompt = ""
    if context:
        full_prompt += (
            "Here is a summary of the existing codebase to help you understand context:\n"
            f"{context}\n\n"
            "Now perform the following task:\n"
        )

    full_prompt += "Write a Python function according to this request:\n\n"
    if system_prompt:
        full_prompt += system_prompt + "\n\n"
    full_prompt += prompt + "\n\n"
    full_prompt += (
        "IMPORTANT: NEVER generate code that writes to or updates README.md. "
        "NEVER create functions like update_readme_for_X(). "
        "README updates are handled by a separate system.\n\n"
        "Return only the Python code (no explanations)."
    )

    # --- Call Gemini or fallback ---
    if genai_available and MODEL_NAME:
        raw = _call_gemini_raw(full_prompt)
    else:
        raw = (
            "def mock_find_max_csv(file_path):\n"
            "    '''Mock function used when Gemini is unavailable.''' \n"
            "    with open(file_path) as f:\n"
            "        nums = [float(line.strip()) for line in f if line.strip()]\n"
            "    return max(nums)\n"
        )

    return clean_gemini_code(raw)

# Sends both the original code and edit instructions to Gemini
    # Gemini returns a newly updated version of the file
    # Used by edit_file_on_github() 
def generate_edit(original_code: str, edit_instructions: str) -> str:
    """
    Ask Gemini to edit the provided code according to edit_instructions.
    Returns cleaned new code.
    """
    full_prompt = (
        "You are given this Python file content:\n\n"
        "----- FILE START -----\n"
        f"{original_code}\n"
        "----- FILE END -----\n\n"
        f"Please make the following changes: {edit_instructions}\n\n"
        "IMPORTANT: NEVER add code that writes to or updates README.md. "
        "NEVER create functions like update_readme_for_X(). "
        "README updates are handled by a separate system.\n\n"
        "Return ONLY the full updated Python file contents (no explanation)."
    )

    if genai_available and MODEL_NAME:
        raw = _call_gemini_raw(full_prompt)
    else:
        # Mock: just append a comment describing the change
        raw = original_code + "\n\n# NOTE: Mock edit: " + edit_instructions + "\n"
    return clean_gemini_code(raw)

def summarize_code(file_path: str, file_content: str, max_retries: int = 3) -> str:
    """
    Asks Gemini to summarize any code file.
    Note: Now that _call_gemini_raw handles retries, we can simplify this,
    but we keep the specific error handling here for safe measure.
    """
    
    # Detect file type from extension
    extension = file_path.split('.')[-1] if '.' in file_path else 'txt'
    
    # Split string to avoid triple backtick issues
    prompt = (
        f"Analyze the following file from a code repository.\n\n"
        f"File Path: {file_path}\n"
        f"File Type: {extension}\n\n"
        f"File Content:\n"
        "```\n"
        f"{file_content}\n"
        "```\n\n"
        "Please provide a concise summary in markdown format. The summary must include:\n\n"
        "1. **Purpose**: A brief (1-2 sentence) description of what this file does.\n"
        "2. **Key Components**:\n"
        "   * List the main functions, classes, or sections\n"
        "   * Describe their inputs (what they take)\n"
        "   * Describe their outputs or side effects (what they return or do)\n"
        "3. **Dependencies**: Any imports or external dependencies used\n\n"
        "Return ONLY the markdown summary."
    )
    
    if not genai_available or not MODEL_NAME:
        return f"_(Gemini not available. Could not summarize {file_path})_"
    
    try:
        return _call_gemini_raw(prompt)
    except Exception as e:
        print(f"Error calling Gemini for {file_path}: {e}")
        return f"_(Error during summarization for {file_path}: {e})_"