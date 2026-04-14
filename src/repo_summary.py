# src/repo_summary.py
import os
from pathlib import Path
from src.gemini_manager import summarize_code
from src.github_manager import get_file, push_file
from src.config import GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH
import sys
import requests
import json

def is_hidden(path: Path) -> bool:
    """Check if a file or directory is hidden."""
    if sys.platform.startswith('win'):
        # On Windows, check FILE_ATTRIBUTE_HIDDEN
        import ctypes
        FILE_ATTRIBUTE_HIDDEN = 0x02
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return False
        return bool(attrs & FILE_ATTRIBUTE_HIDDEN)
    else:
        # On Unix-like systems, hidden if starts with '.'
        return path.name.startswith('.')

def rglob_no_hidden(root: Path, pattern: str):
    """Recursively glob files matching pattern, skipping hidden files/dirs."""
    for p in root.rglob(pattern):
        if not any(is_hidden(parent) for parent in [p] + list(p.parents)):
            yield p

def summarize_repo(owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO, branch: str = GITHUB_BRANCH, output_path: str = None, force_full: bool = False):
    """
    Fetches ALL files from a GitHub repo, generates summaries, and pushes README.
    Only re-summarizes files that have changed since last run.
    
    Args:
        owner: GitHub repo owner
        repo: GitHub repo name
        branch: Branch to analyze
        output_path: Optional local path to save README
        force_full: If True, re-summarize everything (ignore cache)
    """
    if not owner or not repo:
        print("GITHUB_OWNER and GITHUB_REPO must be set in .env")
        return None
    
    # Create checkpoint file path
    repo_root = Path(__file__).resolve().parents[1]
    checkpoint_dir = repo_root / "generated" / ".checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = checkpoint_dir / f"{owner}_{repo}_{branch.replace('/', '_')}_summaries.json"
    
    # Load existing checkpoint if it exists
    checkpoint_data = {
        "summaries": {},  # file_path -> summary
        "shas": {}        # file_path -> sha (to detect changes)
    }
    
    if checkpoint_file.exists() and not force_full:
        try:
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint_data = json.load(f)
            
            # Handle old checkpoint format (backward compatibility)
            if "summaries" not in checkpoint_data:
                checkpoint_data = {
                    "summaries": checkpoint_data,
                    "shas": {}
                }
            
            print(f"Found checkpoint with {len(checkpoint_data['summaries'])} previously summarized files")
        except Exception as e:
            print(f"Could not load checkpoint: {e}")
    elif force_full:
        print(f"Force full re-summarization requested")
    
    print(f"\nFetching files from {owner}/{repo}...")
    
    # Get repository tree from GitHub API
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    
    from src.config import GITHUB_TOKEN
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
        headers["Accept"] = "application/vnd.github.v3+json"
    
    resp = requests.get(url, headers=headers)
    
    if resp.status_code != 200:
        print(f"Failed to fetch repo tree: {resp.status_code}")
        print(f"Response: {resp.text}")
        return None
    
    tree = resp.json().get("tree", [])
    
    print(f"Found {len(tree)} total items in repo")
    
    # Filter for code files (excluding certain paths)
    code_extensions = ['.py', '.js', '.java', '.cpp', '.c', '.h', '.cs', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.ts', '.jsx', '.tsx', '.html', '.css', '.json', '.yaml', '.yml', '.md', '.txt']
    
    # Paths to exclude from summarization
    EXCLUDED_PATHS = [
        "venv/", "site-packages/", "__pycache__/", "node_modules/",
        ".git/", "build/", "dist/",
        "generated/",          # Exclude AI-generated files (agents write here)
        ".checkpoints/",       # Exclude checkpoint metadata
        ".token_cache/",       # Exclude token cache
        "migrations/",         # Exclude DB migrations
    ]
    
    # File patterns to exclude
    EXCLUDED_FILENAMES = [
        "readme.md",           # Never summarize the README itself
        "update_readme",       # Exclude any readme-updater scripts agents may generate
    ]

    code_files = [
        item for item in tree
        if item["type"] == "blob" 
        and any(item["path"].endswith(ext) for ext in code_extensions)
        and not any(x in item["path"] for x in EXCLUDED_PATHS)
        and not any(item["path"].lower().endswith(x) for x in EXCLUDED_FILENAMES)
        and not item["path"].startswith(".")
    ]
    
    print(f"Found {len(code_files)} code files in repo")
    
    if not code_files:
        print(f"No code files found in {owner}/{repo}")
        return None
    
    # Determine which files need to be (re-)summarized
    files_to_process = []
    files_unchanged = []
    files_deleted = []
    
    current_file_paths = {f["path"] for f in code_files}
    previous_file_paths = set(checkpoint_data["summaries"].keys())
    
    for file_info in code_files:
        file_path = file_info["path"]
        current_sha = file_info["sha"]
        previous_sha = checkpoint_data["shas"].get(file_path)
        
        # File is new or changed
        if previous_sha != current_sha:
            files_to_process.append(file_info)
        else:
            files_unchanged.append(file_path)
    
    # Detect deleted files
    files_deleted = previous_file_paths - current_file_paths
    
    # Remove deleted files from checkpoint
    for deleted_file in files_deleted:
        if deleted_file in checkpoint_data["summaries"]:
            del checkpoint_data["summaries"][deleted_file]
        if deleted_file in checkpoint_data["shas"]:
            del checkpoint_data["shas"][deleted_file]
    
    # Print summary
    print(f"\nAnalysis:")
    print(f"  Unchanged: {len(files_unchanged)} files")
    print(f"  New/Modified: {len(files_to_process)} files")
    print(f"  Deleted: {len(files_deleted)} files")
    
    if files_deleted:
        print(f"\n  Deleted files:")
        for df in files_deleted:
            print(f"    - {df}")
    
    if not files_to_process:
        print(f"\nNo new or modified files to summarize!")
    else:
        print(f"\nNeed to summarize {len(files_to_process)} file(s):")
        for f in files_to_process:
            print(f"  - {f['path']}")
    
    # Process files that need summarization
    for file_info in files_to_process:
        file_path = file_info["path"]
        file_sha = file_info["sha"]
        
        try:
            # Fetch file content from GitHub
            content, _ = get_file(file_path, owner=owner, repo=repo, branch=branch)
            
            if not content or not content.strip():
                print(f"Skipping empty file: {file_path}")
                checkpoint_data["summaries"][file_path] = "*Empty file*"
                checkpoint_data["shas"][file_path] = file_sha
                continue
            
            print(f"Summarizing: {file_path}")
            summary = summarize_code(file_path, content)
            
            # Save to checkpoint immediately after each successful summary
            checkpoint_data["summaries"][file_path] = summary
            checkpoint_data["shas"][file_path] = file_sha
            
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, indent=2)
            
            summarized_count = len([f for f in code_files if f["path"] in checkpoint_data["summaries"]])
            print(f"Saved progress ({summarized_count}/{len(code_files)})")
            
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
            checkpoint_data["summaries"][file_path] = f"*Error: {e}*"
            checkpoint_data["shas"][file_path] = file_sha
            
            # Save checkpoint even on error
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, indent=2)
    
    # Build final README from all summaries
    import datetime
    summary_lines = []
    summary_lines.append("# Code Repository Summary\n")
    summary_lines.append("*Auto-generated by Gemini AI*\n")
    summary_lines.append(f"\n**Repository:** {owner}/{repo}\n")
    summary_lines.append(f"**Branch:** {branch}\n")
    summary_lines.append(f"**Files Analyzed:** {len(code_files)}\n")
    summary_lines.append(f"**Last Updated:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    summary_lines.append("<hr>\n")
    
    # Add all summaries in order
    for file_info in code_files:
        file_path = file_info["path"]
        if file_path in checkpoint_data["summaries"]:
            summary_lines.append(f"\n## `{file_path}`\n")
            summary_lines.append(checkpoint_data["summaries"][file_path] + "\n")
            summary_lines.append("<hr>\n")
    
    full_summary = "\n".join(summary_lines)
    
    # Save locally if output_path provided
    if output_path:
        out_path = repo_root / output_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with out_path.open("w", encoding="utf-8") as f:
                f.write(full_summary)
            print(f"\nSummary saved locally to: {out_path}")
        except Exception as e:
            print(f"Could not save locally: {e}")
    
    # Push README to remote repo
    print(f"\nPushing README to {owner}/{repo}...")
    
    try:
        existing_readme, sha = get_file("README.md", owner=owner, repo=repo, branch=branch)
        commit_message = "Update README with code summaries" if existing_readme else "Add README with code summaries"
        
        push_file(
            "README.md",
            full_summary,
            commit_message,
            sha=sha,
            owner=owner,
            repo=repo,
            branch=branch
        )
        
        readme_url = f"https://github.com/{owner}/{repo}/blob/{branch}/README.md"
        print(f"README pushed successfully!")
        print(f"Checkpoint saved for future incremental updates")
        
        return readme_url
        
    except Exception as e:
        print(f"Failed to push to GitHub: {e}")
        import traceback
        traceback.print_exc()
        return output_path if output_path else None