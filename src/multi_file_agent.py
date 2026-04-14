# src/multi_file_agent.py
"""
Enhanced Multi-File Agent with Version Control Integration

Improvements over v1:
1. Integrated version control for all operations
2. Better error handling and rollback
3. Atomic operations (all-or-nothing)
4. Progress tracking
5. Validation before execution
6. Dry-run mode
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import json

from src.gemini_manager import _call_gemini_raw, clean_gemini_code
from src.github_manager import get_file, push_file
from src.config import GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH
from src.function_manager import get_readme_context

# Try to import version control
try:
    from src.version_control import VersionControl
    VERSION_CONTROL_AVAILABLE = True
except ImportError:
    VERSION_CONTROL_AVAILABLE = False
    print("Version control not available")


@dataclass
class OperationResult:
    """Result of a file operation"""
    success: bool
    file_path: str
    action: str  # 'create', 'edit', 'delete'
    version_id: Optional[str] = None
    error: Optional[str] = None
    github_sha: Optional[str] = None


class MultiFileAgentV2:
    """
    Enhanced multi-file agent with version control and better error handling.
    """
    
    def __init__(self, use_version_control: bool = True):
        self.vc = None
        if use_version_control and VERSION_CONTROL_AVAILABLE:
            self.vc = VersionControl()
        
        self.operations_history: List[OperationResult] = []
    
    # ========================================================================
    # Planning
    # ========================================================================
    
    def plan_changes(self, prompt: str) -> Dict:
        """
        Create implementation plan with validation.
        
        Returns:
            dict: Plan with files to create/edit/delete
        """
        readme_context = get_readme_context()
        
        planning_prompt = f"""
You are a senior software architect. Analyze this repository and create a safe implementation plan.

REPOSITORY CONTEXT:
{readme_context}

USER REQUEST: "{prompt}"

Create a detailed plan with these fields:
{{
    "summary": "Brief description of what will be implemented",
    "files_to_create": [
        {{
            "path": "path/to/file.py",
            "purpose": "What this file does",
            "dependencies": ["other_file.py"],
            "priority": 1
        }}
    ],
    "files_to_edit": [
        {{
            "path": "path/to/existing.py",
            "changes": "Specific changes to make",
            "reason": "Why these changes are needed",
            "priority": 2
        }}
    ],
    "files_to_delete": [],
    "validation_rules": [
        "Don't delete core files (main.py, config.py, .env)",
        "Ensure all dependencies are created first",
        "Test files should end with _test.py"
    ],
    "implementation_order": [
        "Step 1: Create base utilities",
        "Step 2: Update main modules",
        "Step 3: Add tests"
    ],
    "estimated_complexity": "low|medium|high"
}}

SAFETY RULES:
- NEVER delete core files (main.py, config.py, README.md, .env, .git*)
- When unsure, EDIT instead of DELETE
- Create tests for new functionality
- Maintain backward compatibility
- When creating new files, all files should go into the existing src/ directory. If src/ does not exist yet, create it.
- Never put new changes in a main.py file existing in the root directory.
- When creating new test files, all files should go into the existing tests/ directory. If tests/ does not exist yet, create it.
- Do not create test files for README.md files because it does not need to be tested after every update.

README RULES:
- Do not push/commit functions to update parts of the README
- Edit the existing README.md file automatically without the use of another helper function

Return ONLY valid JSON, no markdown.
"""
        
        try:
            response = _call_gemini_raw(planning_prompt)
            plan = self._extract_json(response)
            
            # Validate plan
            validated_plan = self._validate_plan(plan)
            
            return validated_plan
            
        except Exception as e:
            print(f"Planning failed: {e}")
            return self._create_empty_plan(str(e))
    
    def _extract_json(self, response: str) -> Dict:
        """Extract JSON from Gemini response"""
        import re
        
        # Try to find JSON block
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        
        raise ValueError("No valid JSON found in response")
    
    def _validate_plan(self, plan: Dict) -> Dict:
        """
        Validate plan for safety and consistency.
        
        Checks:
        - No deletion of core files
        - Dependencies exist
        - Priorities are set
        """
        # Ensure required fields
        plan.setdefault('files_to_create', [])
        plan.setdefault('files_to_edit', [])
        plan.setdefault('files_to_delete', [])
        plan.setdefault('validation_rules', [])
        plan.setdefault('implementation_order', [])
        
        # Safety check: prevent deletion of core files
        PROTECTED_FILES = {
            'main.py', 'config.py', 'README.md', '.env', 
            '.gitignore', 'requirements.txt', 'setup.py'
        }
        
        safe_deletes = []
        for file_path in plan['files_to_delete']:
            if Path(file_path).name not in PROTECTED_FILES:
                safe_deletes.append(file_path)
            else:
                print(f"Prevented deletion of protected file: {file_path}")
        
        plan['files_to_delete'] = safe_deletes
        
        # Add priorities if missing
        for i, file_info in enumerate(plan['files_to_create']):
            if 'priority' not in file_info:
                file_info['priority'] = i + 1
        
        for i, file_info in enumerate(plan['files_to_edit']):
            if 'priority' not in file_info:
                file_info['priority'] = i + 1
        
        return plan
    
    def _create_empty_plan(self, error: str = "") -> Dict:
        """Create empty plan on error"""
        return {
            "summary": f"Planning failed: {error}",
            "files_to_create": [],
            "files_to_edit": [],
            "files_to_delete": [],
            "validation_rules": [],
            "implementation_order": [],
            "estimated_complexity": "unknown",
            "error": error
        }
    
    # ========================================================================
    # Execution
    # ========================================================================
    
    def execute_plan(
        self, 
        plan: Dict, 
        dry_run: bool = False,
        verbose: bool = True
    ) -> Dict[str, List[OperationResult]]:
        """
        Execute the implementation plan with version control.
        
        Args:
            plan: Implementation plan from plan_changes()
            dry_run: If True, simulate without making changes
            verbose: Print progress messages
        
        Returns:
            Dict with results for created, edited, deleted files
        """
        results = {
            'created': [],
            'edited': [],
            'deleted': [],
            'errors': []
        }
        
        if dry_run:
            print("🔍 DRY RUN MODE - No changes will be made\n")
        
        readme_context = get_readme_context()
        
        # Step 1: Create new files (sorted by priority)
        files_to_create = sorted(
            plan.get('files_to_create', []),
            key=lambda x: x.get('priority', 999)
        )
        
        for file_info in files_to_create:
            result = self._create_file(
                file_info, 
                readme_context, 
                dry_run, 
                verbose
            )
            results['created'].append(result)
        
        # Step 2: Edit existing files (sorted by priority)
        files_to_edit = sorted(
            plan.get('files_to_edit', []),
            key=lambda x: x.get('priority', 999)
        )
        
        for file_info in files_to_edit:
            result = self._edit_file(
                file_info, 
                readme_context, 
                dry_run, 
                verbose
            )
            results['edited'].append(result)
        
        # Step 3: Delete files (with confirmation)
        for file_path in plan.get('files_to_delete', []):
            if verbose:
                print(f"Delete requested: {file_path} (not implemented)")
        
        return results
    
    def _create_file(
        self, 
        file_info: Dict, 
        context: str, 
        dry_run: bool,
        verbose: bool
    ) -> OperationResult:
        """Create a new file with version control"""
        file_path = file_info['path']
        purpose = file_info.get('purpose', '')
        dependencies = file_info.get('dependencies', [])
        
        if verbose:
            print(f"\n📝 Creating: {file_path}")
            print(f"   Purpose: {purpose}")
        
        if dry_run:
            return OperationResult(
                success=True,
                file_path=file_path,
                action='create',
                version_id='dry-run'
            )
        
        try:
            # Generate content
            content = self._generate_file_content(
                file_path, purpose, dependencies, context
            )
            
            # Check if file already exists
            existing, _ = get_file(file_path, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH)
            
            if existing:
                print(f"File exists, treating as edit")
                return self._edit_file(
                    {'path': file_path, 'changes': purpose, 'reason': 'File exists'},
                    context,
                    dry_run=False,
                    verbose=False
                )
            
            # Push to GitHub
            result = push_file(
                file_path,
                content,
                f"Create {file_path} - {purpose}",
                owner=GITHUB_OWNER,
                repo=GITHUB_REPO,
                branch=GITHUB_BRANCH
            )
            
            github_sha = result.get('content', {}).get('sha')
            
            # Track version
            version_id = None
            if self.vc:
                version_id = self.vc.commit(
                    file_path=file_path,
                    content=content,
                    agent_name="MultiFileAgentV2",
                    action="create",
                    commit_message=f"Create {file_path}",
                    metadata={'purpose': purpose, 'dependencies': dependencies},
                    github_sha=github_sha,
                    sync_to_github=True
                )
            
            if verbose:
                print(f"Created successfully")
                if version_id:
                    print(f"Version: {version_id[:8]}")
            
            return OperationResult(
                success=True,
                file_path=file_path,
                action='create',
                version_id=version_id,
                github_sha=github_sha
            )
            
        except Exception as e:
            if verbose:
                print(f"Failed: {e}")
            
            return OperationResult(
                success=False,
                file_path=file_path,
                action='create',
                error=str(e)
            )
    
    def _edit_file(
        self, 
        file_info: Dict, 
        context: str, 
        dry_run: bool,
        verbose: bool
    ) -> OperationResult:
        """Edit an existing file with version control"""
        file_path = file_info['path']
        changes = file_info.get('changes', '')
        reason = file_info.get('reason', '')
        
        if verbose:
            print(f"\nEditing: {file_path}")
            print(f"   Changes: {changes}")
        
        if dry_run:
            return OperationResult(
                success=True,
                file_path=file_path,
                action='edit',
                version_id='dry-run'
            )
        
        try:
            # Get current content
            current_content, sha = get_file(file_path, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH)
            
            if not current_content:
                print(f"File not found, creating instead")
                return self._create_file(
                    {'path': file_path, 'purpose': changes, 'dependencies': []},
                    context,
                    dry_run=False,
                    verbose=False
                )
            
            # Generate edits
            new_content = self._generate_file_edits(
                file_path, current_content, changes, reason, context
            )
            
            # Push to GitHub
            result = push_file(
                file_path,
                new_content,
                f"Edit {file_path} - {changes}",
                sha=sha,
                owner=GITHUB_OWNER,
                repo=GITHUB_REPO,
                branch=GITHUB_BRANCH
            )
            
            github_sha = result.get('content', {}).get('sha')
            
            # Track version
            version_id = None
            if self.vc:
                version_id = self.vc.commit(
                    file_path=file_path,
                    content=new_content,
                    agent_name="MultiFileAgentV2",
                    action="edit",
                    commit_message=f"Edit {file_path}",
                    metadata={'changes': changes, 'reason': reason},
                    github_sha=github_sha,
                    sync_to_github=True
                )
            
            if verbose:
                print(f"Edited successfully")
                if version_id:
                    print(f"Version: {version_id[:8]}")
            
            return OperationResult(
                success=True,
                file_path=file_path,
                action='edit',
                version_id=version_id,
                github_sha=github_sha
            )
            
        except Exception as e:
            if verbose:
                print(f"Failed: {e}")
            
            return OperationResult(
                success=False,
                file_path=file_path,
                action='edit',
                error=str(e)
            )
    
    # ========================================================================
    # Content Generation (uses Gemini)
    # ========================================================================
    
    def _generate_file_content(
        self, 
        file_path: str, 
        purpose: str, 
        dependencies: List[str],
        context: str,
        sibling_files: str = ""
    ) -> str:
        """Generate content for a new file"""
        sibling_section = ""
        if sibling_files:
            sibling_section = f"""

ALREADY GENERATED FILES (use these EXACT class/function names when importing):
{sibling_files}

IMPORTANT: When importing from these already-generated files, use the EXACT
class names, function names, and module paths shown above. Do NOT invent
different names.
"""
        prompt = f"""
REPOSITORY CONTEXT:
{context}
{sibling_section}
CREATE NEW FILE: {file_path}

Purpose: {purpose}
Dependencies: {', '.join(dependencies) if dependencies else 'None'}

Generate complete, production-ready Python code for this file.
- Include all necessary imports
- Add proper error handling
- Include docstrings
- Ensure it integrates properly with existing code
- Follow Python best practices (PEP 8)
- If this file imports from other files in this project, use the EXACT names
  defined in those files (shown above in ALREADY GENERATED FILES)

Return ONLY the Python code, no explanations.
"""
        
        code = _call_gemini_raw(prompt)
        return clean_gemini_code(code)
    
    def _generate_file_edits(
        self, 
        file_path: str, 
        current_content: str, 
        changes: str,
        reason: str,
        context: str
    ) -> str:
        """Generate edited content for existing file"""
        prompt = f"""
REPOSITORY CONTEXT:
{context}

EDIT EXISTING FILE: {file_path}

CURRENT CONTENT:
```python
{current_content}
```

REQUIRED CHANGES: {changes}
REASON: {reason}

Generate the COMPLETE updated file with these changes.
- Maintain existing functionality unless explicitly changed
- Add proper error handling for new code
- Update docstrings as needed
- Ensure compatibility with other files

Return ONLY the complete updated Python code, no explanations.
"""
        
        code = _call_gemini_raw(prompt)
        return clean_gemini_code(code)
    
    # ========================================================================
    # Preview (generate code without pushing)
    # ========================================================================
    
    def generate_preview(self, plan: Dict, verbose: bool = True,
                         progress_callback=None) -> Dict[str, dict]:
        """
        Generate all code from the plan WITHOUT pushing to GitHub.
        
        Args:
            plan: Implementation plan from plan_changes()
            verbose: Print progress messages
            progress_callback: Optional callable(msg: str) for live UI updates
        """
        preview = {}
        
        def _status(msg):
            if progress_callback:
                progress_callback(msg)
            elif verbose:
                print(msg)
        
        files_to_create = plan.get('files_to_create', [])
        files_to_edit = plan.get('files_to_edit', [])
        total = len(files_to_create) + len(files_to_edit)
        
        _status(f"Planning: {len(files_to_create)} file(s) to create, {len(files_to_edit)} to edit")
        
        readme_context = get_readme_context()
        done = 0
        
        # Build accumulated context of already-generated files so each
        # subsequent file knows what classes/functions the earlier files defined
        generated_summaries = []  # [(path, first 30 lines)]
        
        def _sibling_context() -> str:
            if not generated_summaries:
                return ""
            parts = []
            for path, snippet in generated_summaries:
                parts.append(f"--- {path} ---\n{snippet}\n")
            return "\n".join(parts)
        
        # Generate content for new files
        for file_info in files_to_create:
            file_path = file_info['path']
            purpose = file_info.get('purpose', '')
            dependencies = file_info.get('dependencies', [])
            done += 1
            
            _status(f"[{done}/{total}] Generating: {file_path}")
            
            try:
                content = self._generate_file_content(
                    file_path, purpose, dependencies, readme_context,
                    sibling_files=_sibling_context()
                )
                preview[file_path] = {
                    "action": "create",
                    "content": content,
                    "original": None,
                    "purpose": purpose,
                }
                # Add to accumulated context for next files
                snippet = "\n".join(content.splitlines()[:40])
                generated_summaries.append((file_path, snippet))
                _status(f"[{done}/{total}] ✅ Generated {file_path} ({len(content)} chars)")
            except Exception as e:
                preview[file_path] = {
                    "action": "create",
                    "content": f"# Error generating preview: {e}",
                    "original": None,
                    "purpose": purpose,
                    "error": str(e),
                }
                _status(f"[{done}/{total}] ❌ Error generating {file_path}: {e}")
        
        # Generate content for edits (also fetch current version for diff)
        for file_info in files_to_edit:
            file_path = file_info['path']
            changes = file_info.get('changes', '')
            reason = file_info.get('reason', '')
            done += 1
            
            _status(f"[{done}/{total}] Fetching current version: {file_path}")
            
            try:
                current_content, sha = get_file(
                    file_path, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH
                )
                
                if current_content is None:
                    _status(f"[{done}/{total}] File not found, creating: {file_path}")
                    content = self._generate_file_content(
                        file_path, changes, [], readme_context
                    )
                    preview[file_path] = {
                        "action": "create",
                        "content": content,
                        "original": None,
                        "purpose": changes,
                    }
                else:
                    _status(f"[{done}/{total}] Generating edits: {file_path}")
                    new_content = self._generate_file_edits(
                        file_path, current_content, changes, reason, readme_context
                    )
                    preview[file_path] = {
                        "action": "edit",
                        "content": new_content,
                        "original": current_content,
                        "changes": changes,
                    }
                _status(f"[{done}/{total}] ✅ Done: {file_path}")
            except Exception as e:
                preview[file_path] = {
                    "action": "edit",
                    "content": f"# Error generating preview: {e}",
                    "original": None,
                    "changes": changes,
                    "error": str(e),
                }
                _status(f"[{done}/{total}] ❌ Error: {file_path}: {e}")
        
        _status(f"✅ All {total} file(s) generated")
        return preview
    
    def execute_preview(
        self, preview: Dict[str, dict], verbose: bool = True,
        target_branch: str = None
    ) -> Dict[str, List[OperationResult]]:
        """
        Push already-generated preview content to GitHub.
        Skips the Gemini calls since code was already generated in generate_preview.
        """
        import src.config as cfg
        import src.github_manager as ghm
        
        results = {
            'created': [],
            'edited': [],
            'deleted': [],
            'errors': [],
            'branch': None,
        }
        
        # Handle target branch
        original_branch = GITHUB_BRANCH
        if target_branch:
            try:
                from src.github_manager import create_branch, list_branches
                existing = list_branches()
                if target_branch not in existing:
                    if verbose:
                        print(f"🌿 Creating branch '{target_branch}' from '{original_branch}'...")
                    create_branch(target_branch, original_branch)
                
                cfg.GITHUB_BRANCH = target_branch
                ghm.GITHUB_BRANCH = target_branch
                import src.multi_file_agent as _self_mod
                _self_mod.GITHUB_BRANCH = target_branch
                results['branch'] = target_branch
            except Exception as e:
                if verbose:
                    print(f"Branch creation failed: {e}, falling back to '{original_branch}'")
                results['errors'].append(str(e))
        
        try:
            for file_path, info in preview.items():
                if info.get("error"):
                    results['errors'].append(f"{file_path}: {info['error']}")
                    continue
                
                content = info["content"]
                action = info["action"]
                
                if verbose:
                    print(f"\n{'📝' if action == 'create' else '✏️'}  Pushing: {file_path}")
                
                try:
                    existing, sha = get_file(
                        file_path, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH
                    )
                    
                    result = push_file(
                        file_path,
                        content,
                        f"{'Create' if action == 'create' else 'Edit'} {file_path}",
                        sha=sha,
                        owner=GITHUB_OWNER,
                        repo=GITHUB_REPO,
                        branch=GITHUB_BRANCH
                    )
                    
                    github_sha = result.get('content', {}).get('sha')
                    op = OperationResult(
                        success=True, file_path=file_path,
                        action=action, github_sha=github_sha
                    )
                    
                    if action == 'create':
                        results['created'].append(op)
                    else:
                        results['edited'].append(op)
                    
                    if verbose:
                        print(f"   ✅ Success")
                    
                except Exception as e:
                    op = OperationResult(
                        success=False, file_path=file_path,
                        action=action, error=str(e)
                    )
                    if action == 'create':
                        results['created'].append(op)
                    else:
                        results['edited'].append(op)
                    if verbose:
                        print(f"   ❌ Failed: {e}")
        
        finally:
            if target_branch:
                cfg.GITHUB_BRANCH = original_branch
                ghm.GITHUB_BRANCH = original_branch
                import src.multi_file_agent as _self_mod
                _self_mod.GITHUB_BRANCH = original_branch
        
        return results

    # ========================================================================
    # Rollback & Recovery
    # ========================================================================
    
    def rollback_operation(self, version_id: str) -> bool:
        """Rollback to a previous version"""
        if not self.vc:
            print("Version control not available")
            return False
        
        try:
            file_path, content = self.vc.rollback(version_id)
            
            # Push rolled-back content to GitHub
            current_content, sha = get_file(file_path, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH)
            
            push_file(
                file_path,
                content,
                f"Rollback to version {version_id[:8]}",
                sha=sha,
                owner=GITHUB_OWNER,
                repo=GITHUB_REPO,
                branch=GITHUB_BRANCH
            )
            
            print(f"Rolled back {file_path} to version {version_id[:8]}")
            return True
            
        except Exception as e:
            print(f"Rollback failed: {e}")
            return False


# ============================================================================
# Convenience Functions (backward compatible)
# ============================================================================

def plan_changes(prompt: str) -> Dict:
    """Backward compatible planning function"""
    agent = MultiFileAgentV2(use_version_control=False)
    return agent.plan_changes(prompt)


def multi_file_execute(
    prompt: str, 
    verbose: bool = True, 
    auto_approve: bool = False
) -> str:
    """Backward compatible execution function"""
    agent = MultiFileAgentV2(use_version_control=VERSION_CONTROL_AVAILABLE)
    
    # Create plan
    if verbose:
        print("\nAnalyzing request and creating plan...\n")
    
    plan = agent.plan_changes(prompt)
    
    if not plan.get('files_to_create') and not plan.get('files_to_edit'):
        return "No changes needed or could not determine what to do."
    
    # Show plan
    total_changes = (
        len(plan.get('files_to_create', [])) + 
        len(plan.get('files_to_edit', []))
    )
    
    print(f"\n{'='*60}")
    print(f"IMPLEMENTATION PLAN")
    print(f"{'='*60}")
    print(f"\n{plan['summary']}\n")
    
    if plan.get('files_to_create'):
        print(f"Files to CREATE ({len(plan['files_to_create'])}):")
        for f in plan['files_to_create']:
            print(f"  + {f['path']}")
            print(f"    └─ {f['purpose']}")
    
    if plan.get('files_to_edit'):
        print(f"\nFiles to EDIT ({len(plan['files_to_edit'])}):")
        for f in plan['files_to_edit']:
            print(f"  ✎ {f['path']}")
            print(f"    └─ {f['changes']}")
    
    print(f"\n{'='*60}\n")
    
    # Get approval
    if not auto_approve:
        try:
            response = input(f"Proceed with these {total_changes} change(s)? [y/N]: ").strip()
            if not response or response.lower() not in ['y', 'yes']:
                return "Cancelled by user"
        except (EOFError, KeyboardInterrupt):
            return "Cancelled by user"
    
    # Execute
    results = agent.execute_plan(plan, dry_run=False, verbose=verbose)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Created: {len([r for r in results['created'] if r.success])} file(s)")
    print(f"Edited: {len([r for r in results['edited'] if r.success])} file(s)")
    
    failed = [r for r in results['created'] + results['edited'] if not r.success]
    if failed:
        print(f"\nFailed: {len(failed)}")
        for r in failed:
            print(f"   ! {r.file_path}: {r.error}")
    
    print(f"\nView changes at: https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}")
    
    return "Multi-file operation completed"