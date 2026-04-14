# src/github_manager.py
import base64
import time
import requests
from typing import Tuple, Optional
from src.config import GITHUB_TOKEN, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH

API_BASE = "https://api.github.com"

def _headers():
    if not GITHUB_TOKEN:
        return {}
    return {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

def get_file(path: str, owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO, branch: str = GITHUB_BRANCH) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns tuple (content_str, sha) if file exists, otherwise (None, None).
    """
    url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": branch}
    resp = requests.get(url, headers=_headers(), params=params)
    if resp.status_code == 200:
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        sha = data["sha"]
        return content, sha
    elif resp.status_code == 404:
        return None, None
    else:
        raise RuntimeError(f"GitHub GET error: {resp.status_code} {resp.text}")


def check_repo_access(owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> dict:
    """
    Check if the current token has access to the repo and what permissions it has.
    """
    result = {"exists": False, "private": False, "read": False, "write": False, "admin": False, "message": ""}
    
    h = _headers()
    if not h:
        result["message"] = "No GitHub token configured"
        return result
    
    resp = requests.get(f"{API_BASE}/repos/{owner}/{repo}", headers=h)
    
    if resp.status_code == 404:
        result["message"] = f"Repository '{owner}/{repo}' not found, or token does not have access to it"
        return result
    elif resp.status_code == 401:
        result["message"] = "GitHub token is invalid or expired"
        return result
    elif resp.status_code != 200:
        result["message"] = f"GitHub API error: {resp.status_code}"
        return result
    
    info = resp.json()
    result["exists"] = True
    result["private"] = info.get("private", False)
    
    perms = info.get("permissions", {})
    result["read"] = perms.get("pull", False)
    result["write"] = perms.get("push", False)
    result["admin"] = perms.get("admin", False)
    
    if not perms:
        result["message"] = "Could not determine permissions (token may lack metadata scope)"
    elif not result["write"]:
        result["message"] = (
            f"Token has READ access to '{owner}/{repo}' but NOT WRITE access. "
            f"{'This is a private repo — token needs `repo` scope.' if result['private'] else 'Token needs `public_repo` or `repo` scope.'}"
        )
    else:
        result["message"] = "Full access"
    
    return result


def push_files_batch(files: list, message: str,
                     owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO,
                     branch: str = GITHUB_BRANCH) -> dict:
    """
    Push multiple files in a SINGLE commit using GitHub's Git Trees API.
    
    Args:
        files: List of dicts with 'path' and 'content' keys
        message: Commit message
        owner, repo, branch: GitHub target
        
    Returns:
        dict with commit info
    
    This avoids triggering N separate CI runs for N files.
    """
    headers = _headers()
    
    # 1. Get the current commit SHA for the branch
    ref_url = f"{API_BASE}/repos/{owner}/{repo}/git/ref/heads/{branch}"
    ref_resp = requests.get(ref_url, headers=headers)
    if ref_resp.status_code != 200:
        raise RuntimeError(f"Failed to get branch ref: {ref_resp.status_code} {ref_resp.text}")
    current_commit_sha = ref_resp.json()["object"]["sha"]
    
    # 2. Get the tree SHA of the current commit
    commit_url = f"{API_BASE}/repos/{owner}/{repo}/git/commits/{current_commit_sha}"
    commit_resp = requests.get(commit_url, headers=headers)
    if commit_resp.status_code != 200:
        raise RuntimeError(f"Failed to get commit: {commit_resp.status_code} {commit_resp.text}")
    base_tree_sha = commit_resp.json()["tree"]["sha"]
    
    # 3. Create blobs for each file
    tree_items = []
    for file_info in files:
        blob_url = f"{API_BASE}/repos/{owner}/{repo}/git/blobs"
        blob_resp = requests.post(blob_url, json={
            "content": file_info["content"],
            "encoding": "utf-8"
        }, headers=headers)
        if blob_resp.status_code != 201:
            raise RuntimeError(f"Failed to create blob for {file_info['path']}: {blob_resp.status_code} {blob_resp.text}")
        blob_sha = blob_resp.json()["sha"]
        tree_items.append({
            "path": file_info["path"],
            "mode": "100644",
            "type": "blob",
            "sha": blob_sha
        })
    
    # 4. Create a new tree
    tree_url = f"{API_BASE}/repos/{owner}/{repo}/git/trees"
    tree_resp = requests.post(tree_url, json={
        "base_tree": base_tree_sha,
        "tree": tree_items
    }, headers=headers)
    if tree_resp.status_code != 201:
        raise RuntimeError(f"Failed to create tree: {tree_resp.status_code} {tree_resp.text}")
    new_tree_sha = tree_resp.json()["sha"]
    
    # 5. Create a new commit
    new_commit_url = f"{API_BASE}/repos/{owner}/{repo}/git/commits"
    new_commit_resp = requests.post(new_commit_url, json={
        "message": message,
        "tree": new_tree_sha,
        "parents": [current_commit_sha]
    }, headers=headers)
    if new_commit_resp.status_code != 201:
        raise RuntimeError(f"Failed to create commit: {new_commit_resp.status_code} {new_commit_resp.text}")
    new_commit_sha = new_commit_resp.json()["sha"]
    
    # 6. Update the branch ref to point to new commit
    # Note: GitHub uses /git/refs/ (plural) for PATCH, not /git/ref/ (singular)
    update_ref_url = f"{API_BASE}/repos/{owner}/{repo}/git/refs/heads/{branch}"
    update_ref_resp = requests.patch(update_ref_url, json={
        "sha": new_commit_sha
    }, headers=headers)
    if update_ref_resp.status_code != 200:
        raise RuntimeError(f"Failed to update ref: {update_ref_resp.status_code} {update_ref_resp.text}")
    
    return {
        "commit_sha": new_commit_sha,
        "files_pushed": len(files),
    }


def push_file(path: str, content: str, message: str, sha: Optional[str] = None,
              owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO, branch: str = GITHUB_BRANCH,
              _retries: int = 3) -> dict:
    """
    Create or update a file on GitHub.
    - Retries on 403 branch protection rule timeouts (up to _retries times)
    - Auto-fetches SHA on 422 "sha wasn't supplied" (file already exists)
    - Auto-initializes empty repos on 404
    """
    url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
    b64 = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {"message": message, "content": b64, "branch": branch}
    if sha:
        payload["sha"] = sha

    for attempt in range(_retries):
        resp = requests.put(url, json=payload, headers=_headers())

        if resp.status_code in (200, 201):
            return resp.json()

        error_body = resp.text

        # ── 403: Branch protection rule timeout → retry with delay ──
        if resp.status_code == 403:
            if "unable to be completed" in error_body.lower() or "rule" in error_body.lower():
                wait = 15 * (attempt + 1)
                print(f"   ⏳ Branch rule timeout on '{path}'. Retrying in {wait}s ({attempt+1}/{_retries})...")
                time.sleep(wait)
                continue
            # Other 403 (actual permission denied) — don't retry
            raise RuntimeError(
                f"Permission denied pushing '{path}'. Check token write access. Error: {error_body}"
            )

        # ── 422: SHA missing → file already exists, fetch SHA and retry ──
        if resp.status_code == 422 and "sha" in error_body.lower():
            print(f"   🔄 '{path}' already exists, fetching SHA to update...")
            _, existing_sha = get_file(path, owner, repo, branch)
            if existing_sha:
                payload["sha"] = existing_sha
                retry_resp = requests.put(url, json=payload, headers=_headers())
                if retry_resp.status_code in (200, 201):
                    return retry_resp.json()
                raise RuntimeError(f"GitHub PUT error after SHA retry: {retry_resp.status_code} {retry_resp.text}")
            raise RuntimeError(f"GitHub PUT 422 — file exists but could not fetch SHA: {error_body}")

        # ── 404: Empty repo → initialize and retry ──
        if resp.status_code == 404:
            if not sha and _initialize_empty_repo(owner, repo, branch):
                retry_resp = requests.put(url, json=payload, headers=_headers())
                if retry_resp.status_code in (200, 201):
                    return retry_resp.json()
            
            access = check_repo_access(owner, repo)
            if not access["exists"]:
                raise RuntimeError(
                    f"Repository '{owner}/{repo}' not found. {access['message']}"
                )
            if not access["write"]:
                raise RuntimeError(
                    f"No write access to '{owner}/{repo}'. {access['message']} "
                    f"Generate a new token with 'repo' scope at https://github.com/settings/tokens"
                )
            raise RuntimeError(
                f"Cannot push to '{path}' on branch '{branch}' in '{owner}/{repo}'. "
                f"The branch may not exist. Try creating it first."
            )

        # ── Other errors → fail immediately ──
        raise RuntimeError(f"GitHub PUT error: {resp.status_code} {error_body}")

    # All retries exhausted (only reached for 403 branch rule timeouts)
    raise RuntimeError(
        f"Failed to push '{path}' after {_retries} retries due to branch protection rule timeouts. "
        f"Ask the repo owner to check Settings → Rules → Rulesets."
    )


def _initialize_empty_repo(owner: str, repo: str, branch: str) -> bool:
    """
    Initialize an empty GitHub repo by creating a README via the low-level Git API.
    """
    try:
        h = _headers()
        
        repo_resp = requests.get(f"{API_BASE}/repos/{owner}/{repo}", headers=h)
        if repo_resp.status_code != 200:
            return False
        
        repo_info = repo_resp.json()
        if repo_info.get("size", 0) > 0:
            return False
        
        print(f"   Initializing empty repo {owner}/{repo}...")
        
        blob_resp = requests.post(
            f"{API_BASE}/repos/{owner}/{repo}/git/blobs",
            json={"content": f"# {repo}\n\nInitialized by Agentic Pipeline.\n", "encoding": "utf-8"},
            headers=h
        )
        if blob_resp.status_code != 201:
            return False
        blob_sha = blob_resp.json()["sha"]
        
        tree_resp = requests.post(
            f"{API_BASE}/repos/{owner}/{repo}/git/trees",
            json={"tree": [{"path": "README.md", "mode": "100644", "type": "blob", "sha": blob_sha}]},
            headers=h
        )
        if tree_resp.status_code != 201:
            return False
        tree_sha = tree_resp.json()["sha"]
        
        commit_resp = requests.post(
            f"{API_BASE}/repos/{owner}/{repo}/git/commits",
            json={"message": "Initial commit", "tree": tree_sha, "parents": []},
            headers=h
        )
        if commit_resp.status_code != 201:
            return False
        commit_sha = commit_resp.json()["sha"]
        
        ref_resp = requests.post(
            f"{API_BASE}/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": commit_sha},
            headers=h
        )
        if ref_resp.status_code == 201:
            print(f"   Repo initialized with README on branch '{branch}'")
            return True
        
        return False
        
    except Exception as e:
        print(f"   Could not initialize repo: {e}")
        return False


def ensure_readme_exists(owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO, branch: str = GITHUB_BRANCH) -> bool:
    """Check if README.md exists in the repo. If not, create a basic one."""
    content, sha = get_file("README.md", owner=owner, repo=repo, branch=branch)
    
    if content is not None:
        return True
    
    try:
        print(f"   📄 Creating README.md in {owner}/{repo}...")
        push_file(
            "README.md",
            f"# {repo}\n\nRepository managed by Agentic Pipeline.\n",
            "Initialize repository with README",
            owner=owner, repo=repo, branch=branch
        )
        print(f"   ✅ README.md created")
        return True
    except Exception as e:
        print(f"   ⚠️  Could not create README.md: {e}")
        return False


def delete_file(path: str, message: str, sha: str,
                owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO, branch: str = GITHUB_BRANCH) -> dict:
    """Delete a file from GitHub. Requires the file's current SHA."""
    url = f"{API_BASE}/repos/{owner}/{repo}/contents/{path}"
    payload = {"message": message, "sha": sha, "branch": branch}
    resp = requests.delete(url, json=payload, headers=_headers())
    if resp.status_code in (200, 204):
        return resp.json() if resp.text else {}
    else:
        raise RuntimeError(f"GitHub DELETE error: {resp.status_code} {resp.text}")

def get_remote_readme(owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO, branch: str = GITHUB_BRANCH) -> str:
    """Fetch the README.md from the remote repository."""
    try:
        content, _ = get_file("README.md", owner=owner, repo=repo, branch=branch)
        return content if content else ""
    except Exception as e:
        print(f"Could not fetch remote README: {e}")
        return ""

def list_branches(owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> list:
    """List all branches in the repository."""
    url = f"{API_BASE}/repos/{owner}/{repo}/branches"
    resp = requests.get(url, headers=_headers(), params={"per_page": 100})
    if resp.status_code == 200:
        return [b["name"] for b in resp.json()]
    else:
        raise RuntimeError(f"GitHub LIST branches error: {resp.status_code} {resp.text}")

def create_branch(new_branch: str, from_branch: str = GITHUB_BRANCH,
                  owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO) -> dict:
    """Create a new branch from an existing branch."""
    url = f"{API_BASE}/repos/{owner}/{repo}/git/ref/heads/{from_branch}"
    resp = requests.get(url, headers=_headers())
    if resp.status_code != 200:
        raise RuntimeError(f"Could not find branch '{from_branch}': {resp.status_code} {resp.text}")
    
    sha = resp.json()["object"]["sha"]
    
    url = f"{API_BASE}/repos/{owner}/{repo}/git/refs"
    payload = {"ref": f"refs/heads/{new_branch}", "sha": sha}
    resp = requests.post(url, json=payload, headers=_headers())
    if resp.status_code == 201:
        return resp.json()
    else:
        raise RuntimeError(f"GitHub CREATE branch error: {resp.status_code} {resp.text}")

def list_repos(owner: str = GITHUB_OWNER) -> list:
    """List repositories for a GitHub user or organization."""
    url = f"{API_BASE}/orgs/{owner}/repos"
    resp = requests.get(url, headers=_headers(), params={"per_page": 100, "sort": "name"})
    
    if resp.status_code == 200:
        return sorted([r["name"] for r in resp.json()])
    
    url = f"{API_BASE}/users/{owner}/repos"
    resp = requests.get(url, headers=_headers(), params={"per_page": 100, "sort": "name"})
    if resp.status_code == 200:
        return sorted([r["name"] for r in resp.json()])
    else:
        raise RuntimeError(f"GitHub LIST repos error: {resp.status_code} {resp.text}")


# ============================================================================
# CI/CD Pipeline Helpers
# ============================================================================

def get_workflow_runs(owner: str = GITHUB_OWNER, repo: str = GITHUB_REPO,
                     branch: str = None, status: str = None,
                     per_page: int = 5) -> list:
    """
    List recent workflow runs, optionally filtered by branch and status.

    Args:
        branch: Filter by branch name (e.g. 'testing/my-feature')
        status: Filter by status ('queued', 'in_progress', 'completed')
        per_page: Max results to return

    Returns:
        List of workflow run dicts from the GitHub API.
    """
    url = f"{API_BASE}/repos/{owner}/{repo}/actions/runs"
    params = {"per_page": per_page}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    resp = requests.get(url, headers=_headers(), params=params)
    if resp.status_code == 200:
        return resp.json().get("workflow_runs", [])
    else:
        raise RuntimeError(f"GitHub GET workflow runs error: {resp.status_code} {resp.text}")


def get_workflow_run_status(run_id: int,
                            owner: str = GITHUB_OWNER,
                            repo: str = GITHUB_REPO) -> dict:
    """
    Get the current status / conclusion of a single workflow run.

    Returns:
        dict with keys 'status' ('queued'|'in_progress'|'completed')
        and 'conclusion' ('success'|'failure'|'cancelled'|None).
    """
    url = f"{API_BASE}/repos/{owner}/{repo}/actions/runs/{run_id}"
    resp = requests.get(url, headers=_headers())
    if resp.status_code == 200:
        data = resp.json()
        return {
            "id": data["id"],
            "status": data["status"],
            "conclusion": data.get("conclusion"),
            "html_url": data["html_url"],
            "created_at": data["created_at"],
            "updated_at": data["updated_at"],
        }
    else:
        raise RuntimeError(f"GitHub GET run status error: {resp.status_code} {resp.text}")


def get_workflow_run_logs(run_id: int,
                          owner: str = GITHUB_OWNER,
                          repo: str = GITHUB_REPO) -> str:
    """
    Download the logs for a workflow run as plain text.

    GitHub returns a redirect to a zip; we follow it, download the zip,
    and extract all log text concatenated together.
    """
    import zipfile, io

    url = f"{API_BASE}/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
    resp = requests.get(url, headers=_headers(), allow_redirects=True)

    if resp.status_code == 200:
        try:
            zf = zipfile.ZipFile(io.BytesIO(resp.content))
            logs = []
            for name in zf.namelist():
                logs.append(f"--- {name} ---\n")
                logs.append(zf.read(name).decode("utf-8", errors="replace"))
            return "\n".join(logs)
        except Exception as e:
            return f"(Could not parse log zip: {e})"
    elif resp.status_code == 404:
        return "(Logs not available yet or run not found)"
    else:
        raise RuntimeError(f"GitHub GET run logs error: {resp.status_code} {resp.text}")


def merge_branch(head: str, base: str, commit_message: str = None,
                 owner: str = GITHUB_OWNER,
                 repo: str = GITHUB_REPO) -> dict:
    """
    Merge *head* branch into *base* branch via the GitHub Merge API.

    Args:
        head: Source branch name (e.g. 'testing/my-feature')
        base: Target branch name (e.g. 'review')
        commit_message: Optional merge commit message

    Returns:
        Merge commit response dict from GitHub API.
    """
    url = f"{API_BASE}/repos/{owner}/{repo}/merges"
    payload = {"base": base, "head": head}
    if commit_message:
        payload["commit_message"] = commit_message
    resp = requests.post(url, json=payload, headers=_headers())

    if resp.status_code in (200, 201):
        return resp.json()
    elif resp.status_code == 204:
        # Base already contains everything in head — nothing to merge.
        return {"message": "already up-to-date"}
    elif resp.status_code == 409:
        raise RuntimeError(f"Merge conflict merging '{head}' → '{base}': {resp.text}")
    else:
        raise RuntimeError(f"GitHub MERGE error: {resp.status_code} {resp.text}")


def delete_branch(branch: str,
                  owner: str = GITHUB_OWNER,
                  repo: str = GITHUB_REPO) -> bool:
    """
    Delete a branch by name.

    Returns True if deleted, False if the branch didn't exist.
    """
    url = f"{API_BASE}/repos/{owner}/{repo}/git/refs/heads/{branch}"
    resp = requests.delete(url, headers=_headers())
    if resp.status_code in (200, 204):
        return True
    elif resp.status_code == 422:
        return False  # Branch doesn't exist
    else:
        raise RuntimeError(f"GitHub DELETE branch error: {resp.status_code} {resp.text}")