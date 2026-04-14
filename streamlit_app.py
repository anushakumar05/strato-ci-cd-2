"""
Streamlit UI for Multi-Agent Codebase Pipeline

TDM Stratolaunch Agentic Project
"""

import streamlit as st
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from src.multi_file_agent import multi_file_execute, plan_changes
from src.repo_summary import summarize_repo
from src.config import GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH, GEMINI_API_KEY, GITHUB_TOKEN
from src.gemini_manager import set_rate_limit_callback
from src.github_manager import list_branches, create_branch, list_repos, check_repo_access


# ============================================================================
# Runtime Overrides (repo, owner, branch)
# ============================================================================

def _get_active_owner() -> str:
    return st.session_state.get("active_owner", GITHUB_OWNER)

def _get_active_repo() -> str:
    return st.session_state.get("active_repo", GITHUB_REPO)

def _get_active_branch() -> str:
    return st.session_state.get("active_branch", GITHUB_BRANCH)


def _set_active_repo(owner: str, repo: str):
    """Update owner+repo everywhere and reset branch list."""
    import src.config as cfg
    import src.github_manager as ghm
    import src.multi_file_agent as mfa
    import src.repo_summary as rs

    st.session_state.active_owner = owner
    st.session_state.active_repo = repo

    cfg.GITHUB_OWNER = owner
    cfg.GITHUB_REPO = repo
    ghm.GITHUB_OWNER = owner
    ghm.GITHUB_REPO = repo
    mfa.GITHUB_OWNER = owner
    mfa.GITHUB_REPO = repo
    rs.GITHUB_OWNER = owner
    rs.GITHUB_REPO = repo

    if "branches_list" in st.session_state:
        del st.session_state.branches_list
    _set_active_branch("main")


def _set_active_branch(branch: str):
    """Update branch everywhere."""
    import src.config as cfg
    import src.github_manager as ghm
    import src.multi_file_agent as mfa
    import src.repo_summary as rs

    st.session_state.active_branch = branch
    cfg.GITHUB_BRANCH = branch
    ghm.GITHUB_BRANCH = branch
    mfa.GITHUB_BRANCH = branch
    rs.GITHUB_BRANCH = branch


# Apply on every Streamlit rerun
if "active_owner" in st.session_state:
    _set_active_repo(st.session_state.active_owner, st.session_state.active_repo)
if "active_branch" in st.session_state:
    _set_active_branch(st.session_state.active_branch)


# ============================================================================
# Rate-Limit Countdown
# ============================================================================

def _streamlit_rate_limit_handler(wait_seconds: float, attempt: int, max_retries: int):
    import time
    import math
    container = st.empty()
    total = int(math.ceil(wait_seconds))
    for remaining in range(total, 0, -1):
        container.warning(
            f"⏳ **API rate limit reached** — "
            f"Retrying in **{remaining}s** "
            f"(attempt {attempt}/{max_retries})"
        )
        time.sleep(1)
    container.info(f"🔄 Retrying... (attempt {attempt}/{max_retries})")

set_rate_limit_callback(_streamlit_rate_limit_handler)


# Page config
st.set_page_config(
    page_title="TDM Stratolaunch Agentic",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header { font-size: 2.5rem; font-weight: bold; color: #1f77b4; margin-bottom: 1rem; }
    .section-header { font-size: 1.5rem; font-weight: bold; color: #ff7f0e; margin-top: 2rem; margin-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# Setup Dialog
# ============================================================================

def _get_effective_token():
    return st.session_state.get("github_token_override") or GITHUB_TOKEN

def _get_effective_gemini_keys():
    if st.session_state.get("gemini_keys_override"):
        return st.session_state["gemini_keys_override"]
    from src.config import GEMINI_API_KEYS
    return GEMINI_API_KEYS

def _apply_credential_overrides():
    import src.config as cfg
    import src.github_manager as ghm
    token = st.session_state.get("github_token_override")
    if token:
        cfg.GITHUB_TOKEN = token
        ghm.GITHUB_TOKEN = token
    gemini_keys = st.session_state.get("gemini_keys_override")
    if gemini_keys:
        cfg.GEMINI_API_KEYS = gemini_keys
        cfg.GEMINI_API_KEY = gemini_keys[0]
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_keys[0])
        except Exception:
            pass
    owner = st.session_state.get("active_owner")
    repo = st.session_state.get("active_repo")
    if owner and repo:
        _set_active_repo(owner, repo)

_apply_credential_overrides()

def _needs_setup() -> bool:
    return not _get_effective_token() or not _get_effective_gemini_keys()

@st.dialog("🔧 Setup Required", width="large")
def _show_setup_dialog():
    st.markdown("Configure your API credentials to get started. These are stored in your browser session only.")
    st.markdown("---")
    st.markdown("### 🔑 GitHub Token")
    st.markdown("Needs `repo` scope for private repos, or `public_repo` for public repos.")
    st.markdown("[Create a token here](https://github.com/settings/tokens/new?scopes=repo)")
    github_token_input = st.text_input(
        "GitHub Personal Access Token", type="password",
        value=st.session_state.get("github_token_override", "") or GITHUB_TOKEN or "",
        key="setup_github_token"
    )
    st.markdown("---")
    st.markdown("### 🤖 Gemini API Key(s)")
    st.markdown("Comma-separated if you have multiple keys for rotation.")
    st.markdown("[Get a key here](https://aistudio.google.com/app/apikey)")
    from src.config import GEMINI_API_KEYS
    existing_keys = st.session_state.get("gemini_keys_override") or GEMINI_API_KEYS or []
    gemini_input = st.text_input(
        "Gemini API Key(s)", type="password",
        value=",".join(existing_keys) if existing_keys else "",
        key="setup_gemini_keys"
    )
    st.markdown("---")
    st.markdown("### 📦 Repository")
    col1, col2 = st.columns(2)
    with col1:
        owner_input = st.text_input("GitHub Owner (user or org)",
            value=st.session_state.get("active_owner") or GITHUB_OWNER or "", key="setup_owner")
    with col2:
        repo_input = st.text_input("Repository name",
            value=st.session_state.get("active_repo") or GITHUB_REPO or "", key="setup_repo")
    st.markdown("---")
    if st.button("✅ Save & Continue", type="primary", use_container_width=True, key="setup_save"):
        errors = []
        if not github_token_input: errors.append("GitHub Token is required")
        if not gemini_input: errors.append("At least one Gemini API Key is required")
        if not owner_input: errors.append("GitHub Owner is required")
        if not repo_input: errors.append("Repository name is required")
        if errors:
            for e in errors: st.error(f"❌ {e}")
        else:
            st.session_state.github_token_override = github_token_input.strip()
            st.session_state.gemini_keys_override = [k.strip() for k in gemini_input.split(",") if k.strip()]
            st.session_state.active_owner = owner_input.strip()
            st.session_state.active_repo = repo_input.strip()
            for key in ["branches_list", f"repos_list_{owner_input.strip()}"]:
                if key in st.session_state: del st.session_state[key]
            _apply_credential_overrides()
            st.rerun()

if _needs_setup():
    _show_setup_dialog()


# ============================================================================
# Sidebar
# ============================================================================

with st.sidebar:
    st.image("https://images.squarespace-cdn.com/content/v1/6810ba591faec6020c63fabc/75b8dc55-6622-4be2-b775-cda3fce68f66/purdue+footer+purdue+logo.png")
    st.markdown("### TDM Stratolaunch")
    st.markdown("**Agentic Project**")
    st.markdown("---")
    st.markdown("**Repository:**")
    st.code(f"{_get_active_owner()}/{_get_active_repo()}")
    st.markdown(f"**Branch:** `{_get_active_branch()}`")
    st.markdown("---")
    st.markdown("**Features:**")
    st.markdown("✅ Multi-file operations")
    st.markdown("✅ Repository summary")
    st.markdown("✅ Settings & config")
    st.markdown("---")
    if _get_active_owner() and _get_active_repo():
        st.markdown(f"[View Repository](https://github.com/{_get_active_owner()}/{_get_active_repo()})")
        st.markdown(f"[View README](https://github.com/{_get_active_owner()}/{_get_active_repo()}/blob/{_get_active_branch()}/README.md)")


# Main header
st.markdown('<div class="main-header">🚀 TDM Stratolaunch Agentic Project</div>', unsafe_allow_html=True)
st.markdown("Automate codebase changes with AI-powered agents")

tab1, tab2, tab3 = st.tabs(["🚀 Multi-File Operations", "📖 Repository Summary", "⚙️ Settings"])


# ============================================================================
# Tab 1: Multi-File Operations
# ============================================================================
with tab1:
    st.markdown('<div class="section-header">Multi-File Operations</div>', unsafe_allow_html=True)
    st.markdown("Execute complex multi-file changes with natural language requests")

    request = st.text_area(
        "Describe what you want to build or change:",
        placeholder="Example: Create a user authentication system with login, registration, and password hashing",
        height=150, key="request_input"
    )

    col1, col2 = st.columns(2)
    with col1:
        verbose = st.checkbox("Show detailed progress", value=True, key="verbose_check")
    with col2:
        auto_approve = st.checkbox("Auto-approve changes", value=False, key="auto_approve_check")

    # Plan button with access pre-check
    if st.button("🔍 Create Plan", type="primary", use_container_width=True, key="plan_button"):
        if not request:
            st.warning("⚠️ Please enter a request first")
        else:
            access = check_repo_access(_get_active_owner(), _get_active_repo())
            if not access["exists"]:
                st.error(
                    f"❌ **Repository not found:** `{_get_active_owner()}/{_get_active_repo()}`\n\n"
                    f"{access['message']}\n\n"
                    f"Go to **Settings → Repository** to change the target, "
                    f"or click **Re-configure Credentials** to update your token."
                )
            elif not access["write"]:
                st.error(
                    f"❌ **No write access** to `{_get_active_owner()}/{_get_active_repo()}`\n\n"
                    f"{access['message']}\n\n"
                    f"[Create a new token with `repo` scope](https://github.com/settings/tokens/new?scopes=repo), "
                    f"then click **Re-configure Credentials** in Settings."
                )
            else:
                with st.spinner("🔍 Analyzing request and creating plan..."):
                    try:
                        plan = plan_changes(request)
                        st.session_state.current_plan = plan
                        st.session_state.current_request = request
                        # Clear any old preview
                        for k in ['code_preview', 'preview_log']:
                            if k in st.session_state: del st.session_state[k]
                    except Exception as e:
                        st.error(f"❌ Error creating plan: {str(e)}")
                        st.exception(e)

    # Display plan if exists
    if 'current_plan' in st.session_state:
        plan = st.session_state.current_plan

        st.markdown("---")
        st.markdown("### 📋 Implementation Plan")
        st.markdown(f"**Summary:** {plan.get('summary', 'No summary available')}")

        col1, col2, col3 = st.columns(3)
        with col1: st.metric("Files to Create", len(plan.get('files_to_create', [])))
        with col2: st.metric("Files to Edit", len(plan.get('files_to_edit', [])))
        with col3: st.metric("Files to Delete", len(plan.get('files_to_delete', [])))

        if plan.get('files_to_create'):
            with st.expander("📁 Files to Create", expanded=True):
                for file in plan['files_to_create']:
                    st.markdown(f"- **{file['path']}**: {file.get('purpose', 'No description')}")
        if plan.get('files_to_edit'):
            with st.expander("✏️ Files to Edit", expanded=True):
                for file in plan['files_to_edit']:
                    st.markdown(f"- **{file['path']}**: {file.get('changes', 'No description')}")
        if plan.get('files_to_delete'):
            with st.expander("🗑️ Files to Delete", expanded=True):
                for file in plan['files_to_delete']:
                    st.markdown(f"- {file}")

        total_changes = (
            len(plan.get('files_to_create', [])) +
            len(plan.get('files_to_edit', [])) +
            len(plan.get('files_to_delete', []))
        )

        if total_changes == 0:
            st.warning("❓ No changes needed")
        else:
            st.markdown("---")

            # ── Branch target ─────────────────────────────────────
            st.markdown("### 🌿 Push Target")
            branch_mode = st.radio(
                "Where should changes be pushed?",
                ["Current branch", "New feature branch"],
                horizontal=True, key="branch_mode"
            )
            feature_branch_name = None
            if branch_mode == "New feature branch":
                import re
                auto_name = re.sub(r'[^a-zA-Z0-9]+', '-', plan.get('summary', 'feature')).strip('-').lower()[:50]
                feature_branch_name = st.text_input(
                    "Branch name", value=f"feature/{auto_name}",
                    help="Changes will be pushed to this new branch",
                    key="feature_branch_input"
                )
                if feature_branch_name:
                    st.info(f"🌿 Changes will be pushed to `{feature_branch_name}` (from `{_get_active_branch()}`)")

            # ── Preview Button ────────────────────────────────────
            st.markdown("### 👁️ Review Code Before Pushing")
            if st.button("🔍 Generate Code Preview", type="secondary", use_container_width=True, key="preview_button"):
                with st.status("🤖 Generating code (does NOT push yet)...", expanded=True) as status_ui:
                    try:
                        from src.multi_file_agent import MultiFileAgentV2
                        import time as _time

                        agent = MultiFileAgentV2(use_version_control=False)
                        gen_log = []
                        gen_start = _time.time()

                        def _progress(msg):
                            elapsed = _time.time() - gen_start
                            entry = f"[{elapsed:.0f}s] {msg}"
                            gen_log.append(entry)
                            status_ui.update(label=f"🤖 {msg}", state="running")
                            st.write(entry)

                        preview = agent.generate_preview(plan, verbose=True, progress_callback=_progress)

                        elapsed = _time.time() - gen_start
                        status_ui.update(label=f"✅ Code generated in {elapsed:.0f}s", state="complete")

                        st.session_state.code_preview = preview
                        st.session_state.preview_log = '\n'.join(gen_log)
                    except Exception as e:
                        status_ui.update(label="❌ Generation failed", state="error")
                        st.error(f"❌ Error generating preview: {str(e)}")
                        st.exception(e)

            # ── Display Preview ───────────────────────────────────
            if 'code_preview' in st.session_state:
                preview = st.session_state.code_preview

                st.markdown("#### Generated Code")
                st.caption("Review below. Nothing has been pushed yet.")

                if st.session_state.get('preview_log'):
                    with st.expander("📜 Generation Log", expanded=False):
                        st.code(st.session_state.preview_log)

                for file_path, info in preview.items():
                    action = info.get("action", "create")
                    icon = "🆕" if action == "create" else "✏️"

                    with st.expander(f"{icon} {file_path}", expanded=True):
                        if info.get("error"):
                            st.error(f"Error: {info['error']}")
                            continue

                        if action == "edit" and info.get("original"):
                            import difflib
                            orig = info["original"].splitlines(keepends=True)
                            new = info["content"].splitlines(keepends=True)
                            diff = difflib.unified_diff(
                                orig, new,
                                fromfile=f"{file_path} (current)",
                                tofile=f"{file_path} (new)",
                                lineterm=""
                            )
                            diff_text = "\n".join(diff)
                            if diff_text:
                                st.markdown("**Diff:**")
                                st.code(diff_text, language="diff")
                            else:
                                st.info("No changes detected")
                            with st.expander("Full new file", expanded=False):
                                st.code(info["content"], language="python")
                        else:
                            st.code(info["content"], language="python")

                st.markdown("---")

                # ── Push previewed code ───────────────────────────
                if st.button(f"✅ Push {len(preview)} File(s) to GitHub", type="primary", use_container_width=True, key="push_preview_btn"):
                    with st.spinner("🔨 Pushing previewed code..."):
                        try:
                            from src.multi_file_agent import MultiFileAgentV2
                            import io
                            from contextlib import redirect_stdout

                            agent = MultiFileAgentV2(use_version_control=False)
                            output = io.StringIO()
                            with redirect_stdout(output):
                                results = agent.execute_preview(
                                    preview, verbose=True,
                                    target_branch=feature_branch_name
                                )

                            st.success("✅ Code pushed!")
                            if feature_branch_name:
                                st.success(f"🌿 Pushed to `{feature_branch_name}`")
                                try: st.session_state.branches_list = list_branches(_get_active_owner(), _get_active_repo())
                                except Exception: pass

                            if verbose:
                                with st.expander("📜 Push Log", expanded=True):
                                    st.code(output.getvalue())

                            created = len([r for r in results.get('created', []) if r.success])
                            edited = len([r for r in results.get('edited', []) if r.success])
                            st.markdown(f"**Created:** {created} | **Edited:** {edited}")

                            failed = [r for r in results.get('created', []) + results.get('edited', []) if not r.success]
                            for r in failed:
                                st.error(f"❌ {r.file_path}: {r.error}")

                            if _get_active_owner() and _get_active_repo():
                                vb = feature_branch_name or _get_active_branch()
                                st.markdown(f"[View Changes on GitHub](https://github.com/{_get_active_owner()}/{_get_active_repo()}/tree/{vb})")

                            for key in ['current_plan', 'current_request', 'code_preview', 'preview_log']:
                                if key in st.session_state: del st.session_state[key]
                        except Exception as e:
                            st.error(f"❌ Error pushing: {str(e)}")
                            st.exception(e)

                # ── CI/CD Pipeline (push → test → fix → review) ──
                st.markdown("---")
                st.markdown("### 🧪 CI/CD Pipeline")
                st.caption("Push to a `testing/*` branch, run CI, auto-fix failures, and promote to `review` when tests pass.")

                cicd_col1, cicd_col2 = st.columns([3, 1])
                with cicd_col1:
                    import re as _re
                    _auto_feat = _re.sub(r'[^a-zA-Z0-9]+', '-',
                                         st.session_state.get('current_plan', {}).get('summary', 'feature')
                                        ).strip('-').lower()[:50]
                    cicd_feature_name = st.text_input(
                        "Feature name (used in branch `testing/<name>`)",
                        value=_auto_feat,
                        key="cicd_feature_name"
                    )
                with cicd_col2:
                    cicd_max_attempts = st.number_input(
                        "Max fix attempts", min_value=1, max_value=10,
                        value=3, key="cicd_max_attempts"
                    )

                if st.button("🧪 Run CI/CD Pipeline", type="secondary", use_container_width=True, key="cicd_run_btn"):
                    with st.spinner("🚀 Running CI/CD pipeline..."):
                        try:
                            from src.ci_cd_pipeline import CICDPipeline, FileChange

                            # Build changes from preview
                            cicd_changes = []
                            for fp, info in preview.items():
                                if info.get("error"):
                                    continue
                                cicd_changes.append(FileChange(
                                    path=fp,
                                    content=info.get("content", ""),
                                    action=info.get("action", "create"),
                                ))

                            if not cicd_changes:
                                st.warning("No valid files to push.")
                            else:
                                status_box = st.empty()
                                log_lines = []

                                def _on_status(stage, msg):
                                    log_lines.append(f"[{stage.upper()}] {msg}")
                                    status_box.info("\n\n".join(log_lines[-6:]))

                                pipeline = CICDPipeline(
                                    owner=_get_active_owner(),
                                    repo=_get_active_repo(),
                                    base_branch=_get_active_branch(),
                                    max_attempts=int(cicd_max_attempts),
                                )
                                result = pipeline.run_pipeline(
                                    cicd_changes, cicd_feature_name,
                                    on_status=_on_status,
                                )

                                if result.success:
                                    st.success(
                                        f"✅ **CI passed** on attempt {result.attempts}! "
                                        f"Code promoted to `{result.review_branch}` branch."
                                    )
                                    st.markdown(
                                        f"[🔍 Review branch on GitHub](https://github.com/"
                                        f"{_get_active_owner()}/{_get_active_repo()}"
                                        f"/tree/{result.review_branch})"
                                    )
                                    if result.ci_url:
                                        st.markdown(f"[📄 CI Run]({result.ci_url})")
                                else:
                                    st.error(f"❌ Pipeline failed at **{result.stage}** stage: {result.message}")
                                    if result.ci_url:
                                        st.markdown(f"[📄 CI Run]({result.ci_url})")
                                    if result.errors:
                                        with st.expander("Error details", expanded=True):
                                            st.code("\n".join(result.errors[:20]))
                                    st.info("💡 **Tip:** Click **🧪 Run CI/CD Pipeline** again to retry with the same generated code — no need to regenerate.")

                                with st.expander("📜 Pipeline Log", expanded=False):
                                    st.code("\n".join(log_lines))
                        except Exception as e:
                            st.error(f"❌ CI/CD error: {str(e)}")
                            st.exception(e)

            # ── Direct execute (skip preview) ─────────────────────
            else:
                st.markdown("---")
                st.caption("Or skip preview and execute directly:")
                if st.button(f"⚡ Execute {total_changes} Change(s) Directly", use_container_width=True, key="execute_button"):
                    with st.spinner("🔨 Executing changes..."):
                        try:
                            import io
                            from contextlib import redirect_stdout
                            output = io.StringIO()
                            with redirect_stdout(output):
                                result = multi_file_execute(
                                    st.session_state.current_request,
                                    verbose=verbose,
                                    auto_approve=True,
                                    target_branch=feature_branch_name
                                )
                            st.success("✅ Operation completed!")
                            if feature_branch_name:
                                st.success(f"🌿 Changes pushed to `{feature_branch_name}`")
                                try: st.session_state.branches_list = list_branches(_get_active_owner(), _get_active_repo())
                                except Exception: pass
                            if verbose:
                                with st.expander("📜 Execution Log", expanded=True):
                                    st.code(output.getvalue())
                            st.markdown(f"**Result:** {result}")
                            if _get_active_owner() and _get_active_repo():
                                vb = feature_branch_name or _get_active_branch()
                                st.markdown(f"[View Changes on GitHub](https://github.com/{_get_active_owner()}/{_get_active_repo()}/tree/{vb})")
                            del st.session_state.current_plan
                            del st.session_state.current_request
                        except Exception as e:
                            st.error(f"❌ Error: {str(e)}")
                            st.exception(e)


# ============================================================================
# Tab 2: Repository Summary
# ============================================================================
with tab2:
    st.markdown('<div class="section-header">Repository Summary</div>', unsafe_allow_html=True)
    st.markdown("Generate AI-powered summaries of your codebase")

    col1, col2 = st.columns(2)
    with col1:
        force_full = st.checkbox("Force full re-summarization", value=False, key="force_full")
    with col2:
        output_local = st.checkbox("Save locally", value=True, key="output_local")

    if st.button("📖 Generate Summary", type="primary", use_container_width=True, key="summary_button"):
        with st.spinner("📝 Analyzing repository and generating summaries..."):
            try:
                import io
                from contextlib import redirect_stdout
                output = io.StringIO()
                with redirect_stdout(output):
                    result_url = summarize_repo(
                        owner=_get_active_owner(), repo=_get_active_repo(),
                        branch=_get_active_branch(),
                        output_path="generated/README.md" if output_local else None,
                        force_full=force_full
                    )
                with st.expander("📜 Summary Generation Log", expanded=False):
                    st.code(output.getvalue())
                if result_url:
                    st.success("✅ Summary generated successfully!")
                    st.markdown(f"[View README on GitHub]({result_url})")
                    if output_local:
                        st.info("💾 Summary also saved locally to generated/README.md")
                else:
                    st.error("❌ Failed to generate summary")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
                st.exception(e)


# ============================================================================
# Tab 3: Settings
# ============================================================================
with tab3:
    st.markdown('<div class="section-header">Settings</div>', unsafe_allow_html=True)

    # Repository Switcher
    st.markdown("### 📦 Repository")
    current_owner = _get_active_owner()
    cache_key = f"repos_list_{current_owner}"
    if cache_key not in st.session_state:
        try:
            st.session_state[cache_key] = list_repos(current_owner)
        except Exception as e:
            st.session_state[cache_key] = [_get_active_repo()]
            st.warning(f"Could not fetch repos for {current_owner}: {e}")

    repos = st.session_state[cache_key]
    active_repo = _get_active_repo()

    new_owner = st.text_input("GitHub Owner (user or org)", value=current_owner, key="owner_input")
    if new_owner and new_owner != current_owner:
        if st.button("Load repos", key="load_repos_btn"):
            try:
                with st.spinner(f"Fetching repos for {new_owner}..."):
                    fetched = list_repos(new_owner)
                st.session_state[f"repos_list_{new_owner}"] = fetched
                _set_active_repo(new_owner, fetched[0] if fetched else "")
                st.success(f"Loaded {len(fetched)} repos for {new_owner}")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to fetch repos: {e}")

    repo_index = repos.index(active_repo) if active_repo in repos else 0
    selected_repo = st.selectbox("Repository", repos, index=repo_index, key="repo_select")
    if selected_repo != active_repo:
        _set_active_repo(current_owner, selected_repo)
        st.success(f"Switched to `{current_owner}/{selected_repo}`")
        st.rerun()

    with st.expander("Current configuration", expanded=False):
        st.code(f"""
Owner: {_get_active_owner()}
Repo: {_get_active_repo()}
Branch: {_get_active_branch()}
Default (from .env): {GITHUB_OWNER}/{GITHUB_REPO} @ {GITHUB_BRANCH}
        """)
        st.info("ℹ️ Defaults come from your .env file. UI overrides are session-only.")

    # Branch Switcher
    st.markdown("### 🌿 Branch")
    if "branches_list" not in st.session_state:
        try:
            st.session_state.branches_list = list_branches(owner=_get_active_owner(), repo=_get_active_repo())
        except Exception as e:
            st.session_state.branches_list = [_get_active_branch()]
            st.warning(f"Could not fetch branches: {e}")

    branches = st.session_state.branches_list
    active = _get_active_branch()
    current_index = branches.index(active) if active in branches else 0
    selected = st.selectbox("Active branch", branches, index=current_index, key="branch_select")
    if selected != active:
        _set_active_branch(selected)
        st.success(f"Switched to branch `{selected}`")
        st.rerun()

    with st.expander("Create new branch", expanded=False):
        new_branch_name = st.text_input("New branch name", placeholder="feature/my-new-feature", key="new_branch_name")
        from_branch = st.selectbox("Branch from", branches, index=current_index, key="from_branch_select")
        if st.button("Create Branch", key="create_branch_btn"):
            if not new_branch_name:
                st.warning("Enter a branch name")
            elif new_branch_name in branches:
                st.warning(f"Branch `{new_branch_name}` already exists")
            else:
                try:
                    with st.spinner(f"Creating `{new_branch_name}` from `{from_branch}`..."):
                        create_branch(new_branch_name, from_branch)
                    st.session_state.branches_list = list_branches(owner=_get_active_owner(), repo=_get_active_repo())
                    _set_active_branch(new_branch_name)
                    st.success(f"Created and switched to `{new_branch_name}`")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to create branch: {e}")

    if st.button("🔄 Refresh branches", key="refresh_branches"):
        try:
            st.session_state.branches_list = list_branches(owner=_get_active_owner(), repo=_get_active_repo())
            st.success("Branch list refreshed")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to refresh: {e}")

    # API Status
    st.markdown("### 🔌 API Status")
    with st.expander("API Configuration", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Gemini API:**")
            keys = _get_effective_gemini_keys()
            if keys:
                st.markdown(f"✅ Configured ({len(keys)} key{'s' if len(keys)>1 else ''})")
            else:
                st.markdown("❌ Not configured")
        with col2:
            st.markdown("**GitHub Token:**")
            token = _get_effective_token()
            if token:
                st.markdown(f"✅ Configured (`{token[:8]}...`)")
            else:
                st.markdown("❌ Not configured")
        if st.session_state.get("github_token_override") or st.session_state.get("gemini_keys_override"):
            st.info("ℹ️ Using session credentials (entered via setup dialog)")

    if st.button("🔧 Re-configure Credentials", use_container_width=True, key="reconfig_btn"):
        _show_setup_dialog()

    # Connection test
    st.markdown("### 🔌 Connection Test")
    if st.button("Test GitHub Access", use_container_width=True, key="test_access_btn"):
        access = check_repo_access(_get_active_owner(), _get_active_repo())
        if not access["exists"]:
            st.error(f"❌ {access['message']}")
        elif not access["write"]:
            st.warning(f"⚠️ Read-only: {access['message']}")
        else:
            st.success(f"✅ Full read/write access to `{_get_active_owner()}/{_get_active_repo()}`")

    # System Info
    st.markdown("### 📊 System Information")
    with st.expander("System Details", expanded=False):
        import platform
        st.code(f"""
Python: {platform.python_version()}
Platform: {platform.platform()}
Working Directory: {Path.cwd()}
        """)

    st.markdown("### 🗑️ Maintenance")
    if st.button("Clear Streamlit Cache", use_container_width=True, key="clear_cache"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.success("✅ Cache cleared!")
        st.rerun()


# Footer
st.markdown("---")
st.markdown(
    f"""
    <div style='text-align: center; color: #666;'>
        TDM Stratolaunch Agentic Project | Built with Streamlit | 
        <a href='https://github.com/{_get_active_owner()}/{_get_active_repo()}' target='_blank'>View Repository</a>
    </div>
    """,
    unsafe_allow_html=True
)