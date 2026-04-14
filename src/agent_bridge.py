# src/agent_bridge.py
"""
Agent Bridge - Unified interface for all agents

This bridge allows LangChain agents to seamlessly use our existing functions
(multi_file_agent, function_manager, etc.) as if they were native LangChain tools.

Benefits:
1. LangChain can use our optimized multi-file workflow
2. Single point of integration - no duplicate tool definitions
3. Automatic context management
4. Consistent error handling
"""

from typing import List, Dict, Any, Callable
from langchain.agents import Tool

# Import all your existing functions
from src.multi_file_agent import plan_changes, multi_file_execute
from src.function_manager import (
    create_file as fm_create,
    edit_file as fm_edit,
    overwrite_file as fm_overwrite,
    get_readme_context
)
from src.github_manager import get_file, push_file
from src.repo_summary import summarize_repo
from src.config import GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH
from src.utils.shared_utils import extract_json_from_response


class AgentBridge:
    """
    Bridge between LangChain and your existing agent functions
    
    Makes all your existing functions available as LangChain tools with:
    - Automatic JSON parsing
    - Context management
    - Error handling
    - Consistent return formats
    """
    
    def __init__(self):
        """Initialize the bridge"""
        self.context_cache = None
    
    # ========================================================================
    # Context Management
    # ========================================================================
    
    def get_context(self, query: str = "") -> str:
        """
        Get repository context (cached)
        
        This is what LangChain agents will call to understand your codebase
        """
        if self.context_cache is None:
            self.context_cache = get_readme_context()
        return self.context_cache or "No context available. Run 'python main.py summarize' first."
    
    def refresh_context(self, query: str = "") -> str:
        """Force refresh context from GitHub"""
        self.context_cache = None
        return self.get_context()
    
    # ========================================================================
    # Multi-File Operations (Your Main Workflow!)
    # ========================================================================
    
    def plan_multi_file_changes(self, request: str) -> str:
        """
        Create implementation plan for multi-file changes
        
        This exposes your multi_file_agent planning to LangChain!
        """
        try:
            plan = plan_changes(request)
            
            # Format plan nicely for LangChain
            summary = plan.get('summary', 'No summary')
            create_count = len(plan.get('files_to_create', []))
            edit_count = len(plan.get('files_to_edit', []))
            delete_count = len(plan.get('files_to_delete', []))
            
            result = f"Plan: {summary}\n\n"
            result += f"Changes: {create_count} create, {edit_count} edit, {delete_count} delete\n\n"
            
            if plan.get('files_to_create'):
                result += "Files to create:\n"
                for f in plan['files_to_create']:
                    result += f"  + {f['path']} - {f['purpose']}\n"
            
            if plan.get('files_to_edit'):
                result += "\nFiles to edit:\n"
                for f in plan['files_to_edit']:
                    result += f"{f['path']} - {f['changes']}\n"
            
            return result
        
        except Exception as e:
            return f"Planning error: {e}"
    
    def execute_multi_file_plan(self, request: str) -> str:
        """
        Plan AND execute multi-file changes
        
        This is your MAIN workflow exposed to LangChain!
        """
        try:
            # Use your existing multi_file_execute (auto-approves in LangChain context)
            result = multi_file_execute(request, verbose=True, auto_approve=True)
            return result
        except Exception as e:
            return f"Execution error: {e}"
    
    # ========================================================================
    # Single File Operations (For Simple Tasks)
    # ========================================================================
    
    def create_single_file(self, input_json: str) -> str:
        """
        Create a single file (uses your function_manager)
        
        Input: {"file_path": "...", "purpose": "..."}
        """
        try:
            params = extract_json_from_response(input_json)
            file_path = params.get('file_path')
            purpose = params.get('purpose', 'No description')
            
            if not file_path:
                return "Error: file_path required"
            
            # Use your existing create_file
            fm_create(file_path, purpose, push_to_github=True)
            return f"Created {file_path}"
        
        except Exception as e:
            return f"Error: {e}"
    
    def edit_single_file(self, input_json: str) -> str:
        """
        Edit a single file (uses your function_manager)
        
        Input: {"file_path": "...", "changes": "..."}
        """
        try:
            params = extract_json_from_response(input_json)
            file_path = params.get('file_path')
            changes = params.get('changes', '')
            
            if not file_path:
                return "Error: file_path required"
            
            # Use your existing edit_file
            fm_edit(file_path, changes, push_to_github=True)
            return f"Edited {file_path}"
        
        except Exception as e:
            return f"Error: {e}"
    
    # ========================================================================
    # Repository Operations
    # ========================================================================
    
    def view_file(self, file_path: str) -> str:
        """View a file from GitHub"""
        try:
            content, sha = get_file(file_path, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH)
            if content:
                # Truncate if too long
                if len(content) > 2000:
                    return f"File: {file_path}\n\n{content[:2000]}\n\n... (truncated, {len(content)} total chars)"
                return f"File: {file_path}\n\n{content}"
            return f"File not found: {file_path}"
        except Exception as e:
            return f"Error: {e}"
    
    def summarize_repository(self, options: str = "") -> str:
        """
        Generate repository summary
        
        Updates README with AI-generated summaries of all files
        """
        try:
            result = summarize_repo(
                owner=GITHUB_OWNER,
                repo=GITHUB_REPO,
                branch=GITHUB_BRANCH
            )
            
            # Refresh context after summarizing
            self.context_cache = None
            
            return f"Repository summarized\n🔗 {result}"
        except Exception as e:
            return f"Error: {e}"
    
    # ========================================================================
    # LangChain Tool Generation
    # ========================================================================
    
    def get_langchain_tools(self) -> List[Tool]:
        """
        Get all tools as LangChain Tool objects
        
        This is what your LangChain agents will use!
        """
        return [
            Tool(
                name="get_repo_context",
                func=self.get_context,
                description=(
                    "Get repository context (README + code summaries). "
                    "ALWAYS call this FIRST to understand the codebase."
                )
            ),
            
            Tool(
                name="multi_file_plan",
                func=self.plan_multi_file_changes,
                description=(
                    "Plan multi-file changes. Input: natural language description. "
                    "Returns a detailed plan of what files will be created/edited/deleted."
                )
            ),
            
            Tool(
                name="multi_file_execute",
                func=self.execute_multi_file_plan,
                description=(
                    "Execute multi-file changes (plan + create/edit files). "
                    "USE THIS for complex requests involving multiple files. "
                    "Input: natural language description. "
                    "Automatically plans and executes all changes."
                )
            ),
            
            Tool(
                name="create_file",
                func=self.create_single_file,
                description=(
                    "Create a SINGLE file. For multi-file tasks, use multi_file_execute instead. "
                    "Input: JSON with file_path and purpose"
                )
            ),
            
            Tool(
                name="edit_file",
                func=self.edit_single_file,
                description=(
                    "Edit a SINGLE file. For multi-file tasks, use multi_file_execute instead. "
                    "Input: JSON with file_path and changes"
                )
            ),
            
            Tool(
                name="view_file",
                func=self.view_file,
                description=(
                    "View file contents from GitHub. "
                    "Input: file path (e.g., 'src/main.py')"
                )
            ),
            
            Tool(
                name="summarize_repo",
                func=self.summarize_repository,
                description=(
                    "Generate AI summaries of all code files and update README. "
                    "Run this after making changes to update documentation."
                )
            ),
            
            Tool(
                name="refresh_context",
                func=self.refresh_context,
                description=(
                    "Force refresh repository context from GitHub. "
                    "Use if you think the context is outdated."
                )
            )
        ]


# ============================================================================
# Global Bridge Instance
# ============================================================================

_bridge = None

def get_agent_bridge() -> AgentBridge:
    """Get or create global AgentBridge instance"""
    global _bridge
    if _bridge is None:
        _bridge = AgentBridge()
    return _bridge


# ============================================================================
# Convenience Functions
# ============================================================================

def get_tools_for_langchain() -> List[Tool]:
    """
    Convenience function: Get all tools for LangChain agents
    
    Usage in your LangChain agent:
        from src.agent_bridge import get_tools_for_langchain
        
        tools = get_tools_for_langchain()
        agent = create_react_agent(llm, tools, prompt)
    """
    return get_agent_bridge().get_langchain_tools()


def register_custom_tool(name: str, func: Callable, description: str):
    """
    Add a custom tool to the bridge
    
    Usage:
        def my_custom_tool(input: str) -> str:
            return "Result"
        
        register_custom_tool(
            "my_tool",
            my_custom_tool,
            "Description of what it does"
        )
    """
    bridge = get_agent_bridge()
    
    # Add to bridge dynamically
    setattr(bridge, name, func)
    
    print(f"Registered custom tool: {name}")