# src/langchain_agent/planning_agent.py
"""
Planning Agent — Adds risk assessment, refinement, and plan-before-execute
workflow on top of the existing MultiFileAgentV2 planning.

This does NOT duplicate any planning or execution logic.  It wraps
MultiFileAgentV2.plan_changes() and MultiFileAgentV2.execute_plan()
and layers on:

    1. Risk assessment  — flags auth/payment/config/delete changes
    2. Plan refinement  — send feedback to Gemini to revise the plan
    3. Save/load        — persist plans as JSON for later review
    4. CLI separation   — `python main.py plan "goal"` creates a plan
                          without executing; add --execute to run it

Everything flows through your existing infrastructure:
    plan_changes()  → existing Gemini prompt + validation
    execute_plan()  → existing file creation/editing + version control
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from enum import Enum

from src.gemini_manager import _call_gemini_raw
from src.multi_file_agent import MultiFileAgentV2, plan_changes as existing_plan_changes
from src.utils.shared_utils import extract_json_from_response


# ============================================================================
# Risk Assessment (the main thing multi_file_agent doesn't have)
# ============================================================================

class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Patterns matched against file paths + descriptions
_RISK_PATTERNS = {
    RiskLevel.CRITICAL: [
        r"auth", r"password", r"secret", r"token", r"crypt",
        r"payment", r"billing", r"charge",
        r"database.*migrat", r"schema.*change",
    ],
    RiskLevel.HIGH: [
        r"delete", r"remove", r"config", r"deploy",
        r"\.env", r"security", r"permission", r"credential",
    ],
    RiskLevel.MEDIUM: [
        r"refactor", r"rename", r"restructure",
        r"dependency", r"interface.*change",
    ],
}

PROTECTED_FILES = frozenset({
    "main.py", "config.py", "README.md", ".env",
    ".gitignore", "requirements.txt", "setup.py",
})

_RISK_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}


def assess_file_risk(file_path: str, description: str, action: str) -> Tuple[RiskLevel, str]:
    """Assess risk for a single file operation."""
    text = f"{file_path} {description}".lower()

    if action == "delete":
        if Path(file_path).name in PROTECTED_FILES:
            return RiskLevel.CRITICAL, "Deletes a protected core file"
        return RiskLevel.HIGH, "File deletion is irreversible without version control"

    for level in (RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM):
        for pattern in _RISK_PATTERNS.get(level, []):
            if re.search(pattern, text):
                return level, f"Matches risk pattern: {pattern}"

    return RiskLevel.LOW, ""


def assess_plan_risk(plan: Dict) -> Dict:
    """
    Add risk metadata to an existing plan dict (from plan_changes).

    Mutates the plan in-place and returns it with added fields:
        plan["risk_level"]    — overall risk string
        plan["risk_warnings"] — list of warning strings
        Each file entry gets "risk_level" and "risk_reason"
    """
    warnings = []
    max_risk = RiskLevel.LOW

    for file_entry in plan.get("files_to_create", []):
        risk, reason = assess_file_risk(
            file_entry["path"], file_entry.get("purpose", ""), "create"
        )
        file_entry["risk_level"] = risk.value
        file_entry["risk_reason"] = reason
        if _RISK_RANK[risk] > _RISK_RANK[max_risk]:
            max_risk = risk
        if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            warnings.append(f"[{risk.value.upper()}] CREATE {file_entry['path']}: {reason}")

    for file_entry in plan.get("files_to_edit", []):
        risk, reason = assess_file_risk(
            file_entry["path"], file_entry.get("changes", ""), "edit"
        )
        file_entry["risk_level"] = risk.value
        file_entry["risk_reason"] = reason
        if _RISK_RANK[risk] > _RISK_RANK[max_risk]:
            max_risk = risk
        if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            warnings.append(f"[{risk.value.upper()}] EDIT {file_entry['path']}: {reason}")

    for file_path in plan.get("files_to_delete", []):
        risk, reason = assess_file_risk(file_path, "", "delete")
        if _RISK_RANK[risk] > _RISK_RANK[max_risk]:
            max_risk = risk
        if risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            warnings.append(f"[{risk.value.upper()}] DELETE {file_path}: {reason}")

    plan["risk_level"] = max_risk.value
    plan["risk_warnings"] = warnings
    return plan


# ============================================================================
# Plan Refinement (iterative — sends existing plan + feedback back to Gemini)
# ============================================================================

def refine_plan(plan: Dict, feedback: str) -> Dict:
    """
    Send the current plan + user feedback to Gemini and get a revised plan.
    The result goes through the same validation as the original.
    """
    # Trim plan content sent to Gemini (no need to send risk metadata)
    plan_for_gemini = {
        "summary": plan.get("summary"),
        "files_to_create": [
            {"path": f["path"], "purpose": f.get("purpose", "")}
            for f in plan.get("files_to_create", [])
        ],
        "files_to_edit": [
            {"path": f["path"], "changes": f.get("changes", ""), "reason": f.get("reason", "")}
            for f in plan.get("files_to_edit", [])
        ],
        "files_to_delete": plan.get("files_to_delete", []),
    }

    prompt = f"""You are revising an implementation plan based on user feedback.

CURRENT PLAN:
{json.dumps(plan_for_gemini, indent=2)}

USER FEEDBACK: "{feedback}"

Produce a revised plan with the same JSON structure. Adjust files, purposes,
and changes according to the feedback.  Keep file paths stable where possible.

Return ONLY valid JSON with keys: summary, files_to_create, files_to_edit,
files_to_delete, implementation_order, estimated_complexity.
No markdown fences, no explanation."""

    response = _call_gemini_raw(prompt)
    raw = extract_json_from_response(response, default=None)

    if not raw or (not raw.get("files_to_create") and not raw.get("files_to_edit")):
        print("  Could not parse refinement — returning original plan.")
        return plan

    # Run through the same validation the original plan gets
    agent = MultiFileAgentV2(use_version_control=False)
    validated = agent._validate_plan(raw)
    return assess_plan_risk(validated)


# ============================================================================
# Save / Load
# ============================================================================

def save_plan(plan: Dict, path: str = None) -> str:
    """Save a plan dict to JSON."""
    if path is None:
        plan_dir = Path("generated") / ".plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        plan_id = f"plan_{int(time.time())}"
        path = str(plan_dir / f"{plan_id}.json")

    # Add timestamp
    plan.setdefault("saved_at", datetime.now().isoformat())

    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, default=str)

    print(f"  Plan saved to {path}")
    return path


def load_plan(path: str) -> Dict:
    """Load a plan dict from JSON."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================================
# Pretty-Print
# ============================================================================

def print_plan(plan: Dict):
    """Pretty-print a plan dict to stdout."""
    risk_icons = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}

    risk = plan.get("risk_level", "low")
    print(f"\n{'='*60}")
    print(f"  PLAN  {risk_icons.get(risk, '⚪')} Risk: {risk.upper()}")
    print(f"{'='*60}")
    print(f"\n  {plan.get('summary', 'No summary')}\n")

    creates = plan.get("files_to_create", [])
    edits = plan.get("files_to_edit", [])
    deletes = plan.get("files_to_delete", [])

    if creates:
        print(f"  CREATE ({len(creates)}):")
        for f in creates:
            ri = risk_icons.get(f.get("risk_level", "low"), "⚪")
            print(f"    {ri} + {f['path']}")
            print(f"        {f.get('purpose', '')}")
            if f.get("risk_reason"):
                print(f"        ⚠  {f['risk_reason']}")

    if edits:
        print(f"\n  EDIT ({len(edits)}):")
        for f in edits:
            ri = risk_icons.get(f.get("risk_level", "low"), "⚪")
            print(f"    {ri} ✎ {f['path']}")
            print(f"        {f.get('changes', '')}")
            if f.get("risk_reason"):
                print(f"        ⚠  {f['risk_reason']}")

    if deletes:
        print(f"\n  DELETE ({len(deletes)}):")
        for fp in deletes:
            print(f"    🔴 - {fp}")

    warnings = plan.get("risk_warnings", [])
    if warnings:
        print(f"\n  WARNINGS:")
        for w in warnings:
            print(f"    ⚠  {w}")

    order = plan.get("implementation_order", [])
    if order:
        print(f"\n  ORDER:")
        for step in order:
            print(f"    {step}")

    total = len(creates) + len(edits) + len(deletes)
    print(f"\n  Total operations: {total}")
    print(f"{'='*60}\n")


# ============================================================================
# Auto-Summarize (update README after execution)
# ============================================================================

def _auto_summarize():
    """Run summarize_repo after plan execution to keep README current."""
    try:
        from src.repo_summary import summarize_repo
        from src.config import GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH

        print("\nUpdating README with new summaries...")
        result = summarize_repo(
            owner=GITHUB_OWNER, repo=GITHUB_REPO, branch=GITHUB_BRANCH
        )
        if result:
            print(f"README updated: {result}")
        else:
            print("README update returned no result.")
    except Exception as e:
        print(f"Auto-summarize failed (non-fatal): {e}")


# ============================================================================
# LangChain Tools
# ============================================================================

_last_plan: Optional[Dict] = None


def _tool_create_plan(goal: str) -> str:
    """Create a risk-assessed plan from a goal."""
    global _last_plan
    plan = existing_plan_changes(goal)
    _last_plan = assess_plan_risk(plan)

    lines = [f"Plan: {_last_plan.get('summary', goal)}"]
    lines.append(f"Risk: {_last_plan.get('risk_level', 'unknown')}")
    lines.append(f"Create: {len(_last_plan.get('files_to_create', []))}")
    lines.append(f"Edit: {len(_last_plan.get('files_to_edit', []))}")
    for w in _last_plan.get("risk_warnings", []):
        lines.append(f"  ⚠ {w}")
    return "\n".join(lines)


def _tool_refine(feedback: str) -> str:
    """Refine the most recent plan based on feedback."""
    global _last_plan
    if not _last_plan:
        return "No plan exists yet. Use create_plan first."
    _last_plan = refine_plan(_last_plan, feedback)
    return _tool_show_plan("")


def _tool_execute(confirmation: str = "yes") -> str:
    """Execute the most recent plan."""
    global _last_plan
    if not _last_plan:
        return "No plan exists yet. Use create_plan first."

    risk = _last_plan.get("risk_level", "low")
    if risk in ("high", "critical") and confirmation.lower() not in ("yes", "y"):
        return (
            f"Plan has {risk.upper()} risk. Send 'yes' to confirm.\n"
            + "\n".join(_last_plan.get("risk_warnings", []))
        )

    try:
        from src.agent_os.version_control import VersionControl
        use_vc = True
    except ImportError:
        use_vc = False

    agent = MultiFileAgentV2(use_version_control=use_vc)
    results = agent.execute_plan(_last_plan, verbose=True)

    created = len([r for r in results.get("created", []) if hasattr(r, "success") and r.success])
    edited = len([r for r in results.get("edited", []) if hasattr(r, "success") and r.success])

    if created > 0 or edited > 0:
        _auto_summarize()

    return f"Done. Created {created}, edited {edited} file(s)."


def _tool_show_plan(query: str = "") -> str:
    """Return a text summary of the current plan."""
    if not _last_plan:
        return "No plan exists yet. Use create_plan first."
    lines = [
        f"Plan: {_last_plan.get('summary', '')}",
        f"Risk: {_last_plan.get('risk_level', 'unknown')}",
    ]
    for f in _last_plan.get("files_to_create", []):
        lines.append(f"  + {f['path']} — {f.get('purpose', '')}")
    for f in _last_plan.get("files_to_edit", []):
        lines.append(f"  ✎ {f['path']} — {f.get('changes', '')}")
    for fp in _last_plan.get("files_to_delete", []):
        lines.append(f"  - {fp}")
    for w in _last_plan.get("risk_warnings", []):
        lines.append(f"  ⚠ {w}")
    return "\n".join(lines)


def get_planning_tools():
    """Get LangChain Tool objects for planning."""
    from langchain.agents import Tool

    return [
        Tool(name="create_plan", func=_tool_create_plan,
             description="Create a risk-assessed implementation plan. Input: goal description. "
                         "Use BEFORE executing to review what will change."),
        Tool(name="refine_plan", func=_tool_refine,
             description="Refine the current plan. Input: feedback on what to change."),
        Tool(name="execute_plan", func=_tool_execute,
             description="Execute the current plan. Input: 'yes' to confirm. "
                         "High-risk plans require explicit confirmation."),
        Tool(name="show_plan", func=_tool_show_plan,
             description="Show the current plan with risk assessment."),
    ]


def register_planning_tools():
    """Register planning tools with the existing AgentBridge."""
    try:
        from src.agent_bridge import get_agent_bridge
        bridge = get_agent_bridge()
        bridge.create_plan = _tool_create_plan
        bridge.refine_plan = _tool_refine
        bridge.execute_plan_reviewed = _tool_execute
        bridge.show_plan = _tool_show_plan
        print("  Planning tools registered with AgentBridge.")
    except Exception as e:
        print(f"  Could not register planning tools: {e}")


# ============================================================================
# CLI Entry Point (called from main.py)
# ============================================================================

def plan_cli(goal: str, execute: bool = False, auto_approve: bool = False,
             verbose: bool = True) -> str:
    """
    CLI workflow:
        python main.py plan "Add JWT auth"              # plan only
        python main.py plan "Add JWT auth" --execute     # plan + execute
        python main.py plan "Add JWT auth" -x -y         # plan + execute, skip confirm
    """
    # Use the existing planning from MultiFileAgentV2
    plan = existing_plan_changes(goal)
    plan = assess_plan_risk(plan)

    if verbose:
        print_plan(plan)

    path = save_plan(plan)

    if not plan.get("files_to_create") and not plan.get("files_to_edit"):
        return "No changes needed."

    if not execute:
        return (
            f"Plan saved to {path}. "
            f"Review it, then run with --execute to apply."
        )

    # Confirm
    risk = plan.get("risk_level", "low")
    total = len(plan.get("files_to_create", [])) + len(plan.get("files_to_edit", []))

    if not auto_approve:
        label = f"⚠ {risk.upper()} RISK — " if risk in ("high", "critical") else ""
        try:
            resp = input(f"{label}Execute {total} operations? [y/N]: ").strip()
            if resp.lower() not in ("y", "yes"):
                return "Cancelled."
        except (EOFError, KeyboardInterrupt):
            return "Cancelled."

    # Execute using existing infrastructure
    try:
        from src.agent_os.version_control import VersionControl
        use_vc = True
    except ImportError:
        use_vc = False

    agent = MultiFileAgentV2(use_version_control=use_vc)
    results = agent.execute_plan(plan, verbose=verbose)

    created = len([r for r in results.get("created", []) if hasattr(r, "success") and r.success])
    edited = len([r for r in results.get("edited", []) if hasattr(r, "success") and r.success])
    failed = [r for r in results.get("created", []) + results.get("edited", [])
              if hasattr(r, "success") and not r.success]

    save_plan(plan, path)  # re-save with any updated metadata

    # Auto-summarize README after successful changes
    if created > 0 or edited > 0:
        _auto_summarize()

    msg = f"Done. Created {created}, edited {edited} file(s)."
    if failed:
        msg += f" Failed: {len(failed)}."
    return msg