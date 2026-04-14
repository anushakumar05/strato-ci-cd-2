# src/agent_os/version_control.py
"""
Integrated Version Control System for Agent OS

Integrates with:
- Gemini context (README, repo summaries)
- GitHub sync (automatic push)
- Agent OS (tracks all agent actions)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
import hashlib


@dataclass
class Version:
    """Represents a single version/snapshot of a file."""
    version_id: str
    file_path: str
    content: str
    content_hash: str
    timestamp: str
    agent_name: str
    action: str  # 'create', 'edit', 'overwrite'
    commit_message: str
    metadata: Dict[str, Any]
    parent_version_id: Optional[str] = None
    github_sha: Optional[str] = None  # GitHub SHA after sync
    synced_to_github: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Version':
        """Create Version from dictionary."""
        return cls(**data)


class VersionControl:
    """
    Integrated version control system.
    
    Features:
    - Tracks all file changes
    - Integrates with GitHub
    - Provides history context to Gemini
    - Rollback support
    """
    
    def __init__(self, storage_dir: str = ".agent_os_versions"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)
        
        self.file_history: Dict[str, List[str]] = {}
        self.versions: Dict[str, Version] = {}
        
        self._load_version_data()
    
    def _generate_version_id(self, file_path: str, content: str, timestamp: str) -> str:
        """Generate unique version ID."""
        data = f"{file_path}:{content[:100]}:{timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def _compute_content_hash(self, content: str) -> str:
        """Compute hash of file content."""
        return hashlib.sha256(content.encode()).hexdigest()
    
    def commit(self, 
               file_path: str, 
               content: str, 
               agent_name: str, 
               action: str,
               commit_message: str = "",
               metadata: Dict[str, Any] = None,
               sync_to_github: bool = True) -> str:
        """
        Commit a new version and optionally sync to GitHub.
        
        Args:
            file_path: Path to the file
            content: File content
            agent_name: Name of agent making the change
            action: Type of action ('create', 'edit', 'overwrite')
            commit_message: Optional commit message
            metadata: Optional metadata (plan, prompt, etc.)
            sync_to_github: Whether to push to GitHub immediately
            
        Returns:
            version_id of the new version
        """
        timestamp = datetime.now().isoformat()
        content_hash = self._compute_content_hash(content)
        version_id = self._generate_version_id(file_path, content, timestamp)
        
        # Get parent version
        parent_version_id = None
        if file_path in self.file_history and self.file_history[file_path]:
            parent_version_id = self.file_history[file_path][-1]
        
        # Create version
        version = Version(
            version_id=version_id,
            file_path=file_path,
            content=content,
            content_hash=content_hash,
            timestamp=timestamp,
            agent_name=agent_name,
            action=action,
            commit_message=commit_message or f"{action.capitalize()} {file_path}",
            metadata=metadata or {},
            parent_version_id=parent_version_id,
            synced_to_github=False
        )
        
        # Sync to GitHub if requested
        if sync_to_github:
            github_sha = self._sync_to_github(version)
            if github_sha:
                version.github_sha = github_sha
                version.synced_to_github = True
        
        # Store version
        self.versions[version_id] = version
        
        # Update file history
        if file_path not in self.file_history:
            self.file_history[file_path] = []
        self.file_history[file_path].append(version_id)
        
        # Persist to disk
        self._save_version(version)
        self._save_version_data()
        
        status_icon = "🔄" if version.synced_to_github else "💾"
        print(f"{status_icon} Version: {version_id[:8]} - {file_path}")
        
        return version_id
    
    def _sync_to_github(self, version: Version) -> Optional[str]:
        """
        Sync a version to GitHub using YOUR EXISTING push_file function.
        
        This uses:
        - get_file() from your github_manager.py
        - push_file() from your github_manager.py
        
        Args:
            version: Version to sync
            
        Returns:
            GitHub SHA if successful, None otherwise
        """
        try:
            # Import YOUR existing functions
            from src.github_manager import push_file, get_file
            from src.config import GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH
            
            # Check if file exists on GitHub (using YOUR get_file)
            existing_content, existing_sha = get_file(
                version.file_path,
                owner=GITHUB_OWNER,
                repo=GITHUB_REPO,
                branch=GITHUB_BRANCH
            )
            
            # Push to GitHub (using YOUR push_file)
            # This is the same function you've been using!
            result = push_file(
                version.file_path,
                version.content,
                version.commit_message,
                sha=existing_sha,  # Update if exists, create if new
                owner=GITHUB_OWNER,
                repo=GITHUB_REPO,
                branch=GITHUB_BRANCH
            )
            
            # Extract SHA from result
            if result and 'content' in result:
                github_sha = result['content'].get('sha')
                print(f"   ✅ Synced to GitHub (SHA: {github_sha[:8] if github_sha else 'unknown'})")
                return github_sha
            
            return None
        
        except Exception as e:
            print(f"   ⚠️ GitHub sync failed: {e}")
            return None
    
    def get_version(self, version_id: str) -> Optional[Version]:
        """Get a specific version by ID."""
        return self.versions.get(version_id)
    
    def get_file_history(self, file_path: str) -> List[Version]:
        """Get complete history of a file."""
        if file_path not in self.file_history:
            return []
        
        version_ids = self.file_history[file_path]
        return [self.versions[vid] for vid in version_ids if vid in self.versions]
    
    def get_latest_version(self, file_path: str) -> Optional[Version]:
        """Get the latest version of a file."""
        history = self.get_file_history(file_path)
        return history[-1] if history else None
    
    def get_context_for_gemini(self, file_path: str = None, limit: int = 5) -> str:
        """
        Generate context string for Gemini based on version history.
        
        Args:
            file_path: Optional specific file to get context for
            limit: Number of recent versions to include
            
        Returns:
            Formatted context string for Gemini
        """
        context_parts = ["# Version Control Context\n"]
        
        if file_path:
            # Context for specific file
            history = self.get_file_history(file_path)[-limit:]
            if history:
                context_parts.append(f"\n## History of {file_path}:\n")
                for v in history:
                    context_parts.append(
                        f"- Version {v.version_id[:8]} ({v.timestamp})\n"
                        f"  Agent: {v.agent_name}\n"
                        f"  Action: {v.action}\n"
                        f"  Message: {v.commit_message}\n"
                    )
        else:
            # General context - recent activity across all files
            all_versions = sorted(
                self.versions.values(),
                key=lambda v: v.timestamp,
                reverse=True
            )[:limit]
            
            if all_versions:
                context_parts.append("\n## Recent Changes:\n")
                for v in all_versions:
                    context_parts.append(
                        f"- {v.file_path} (Version {v.version_id[:8]})\n"
                        f"  {v.action} by {v.agent_name}\n"
                        f"  {v.commit_message}\n"
                    )
        
        return "".join(context_parts)
    
    def rollback(self, file_path: str, version_id: str, sync_to_github: bool = True) -> Version:
        """
        Rollback a file to a previous version.
        
        Args:
            file_path: Path to file
            version_id: Version ID to rollback to
            sync_to_github: Whether to sync rollback to GitHub
            
        Returns:
            New Version object (the rollback commit)
        """
        old_version = self.get_version(version_id)
        if not old_version:
            raise ValueError(f"Version {version_id} not found")
        
        if old_version.file_path != file_path:
            raise ValueError(f"Version {version_id} is not for file {file_path}")
        
        # Create new version with old content
        new_version_id = self.commit(
            file_path=file_path,
            content=old_version.content,
            agent_name="VersionControl",
            action="rollback",
            commit_message=f"Rollback to version {version_id[:8]}",
            metadata={
                'rollback_to': version_id,
                'rollback_from': self.get_latest_version(file_path).version_id
            },
            sync_to_github=sync_to_github
        )
        
        print(f"🔄 Rolled back {file_path} to version {version_id[:8]}")
        
        return self.get_version(new_version_id)
    
    def print_history(self, file_path: str, limit: int = 10):
        """Print version history for a file."""
        history = self.get_file_history(file_path)
        
        if not history:
            print(f"No version history for {file_path}")
            return
        
        print(f"\n📜 Version History: {file_path}")
        print("=" * 80)
        
        for version in history[-limit:]:
            sync_status = "✅ GitHub" if version.synced_to_github else "💾 Local"
            print(f"\n🔹 Version: {version.version_id[:8]} {sync_status}")
            print(f"   Timestamp: {version.timestamp}")
            print(f"   Agent: {version.agent_name}")
            print(f"   Action: {version.action}")
            print(f"   Message: {version.commit_message}")
            if version.github_sha:
                print(f"   GitHub SHA: {version.github_sha[:8]}")
        
        print("\n" + "=" * 80)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get version control statistics."""
        synced_count = sum(1 for v in self.versions.values() if v.synced_to_github)
        
        return {
            'total_versions': len(self.versions),
            'synced_to_github': synced_count,
            'local_only': len(self.versions) - synced_count,
            'total_files': len(self.file_history),
            'agents': list(set(v.agent_name for v in self.versions.values())),
            'actions': {
                'create': sum(1 for v in self.versions.values() if v.action == 'create'),
                'edit': sum(1 for v in self.versions.values() if v.action == 'edit'),
                'overwrite': sum(1 for v in self.versions.values() if v.action == 'overwrite'),
                'rollback': sum(1 for v in self.versions.values() if v.action == 'rollback')
            }
        }
    
    # --- Persistence methods ---
    
    def _save_version(self, version: Version):
        """Save a single version to disk."""
        version_file = self.storage_dir / f"{version.version_id}.json"
        with open(version_file, 'w') as f:
            json.dump(version.to_dict(), f, indent=2)
    
    def _save_version_data(self):
        """Save version metadata."""
        metadata_file = self.storage_dir / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump({
                'file_history': self.file_history,
                'version_index': list(self.versions.keys()),
                'last_updated': datetime.now().isoformat()
            }, f, indent=2)
    
    def _load_version_data(self):
        """Load version data from disk."""
        metadata_file = self.storage_dir / "metadata.json"
        
        if not metadata_file.exists():
            return
        
        try:
            with open(metadata_file, 'r') as f:
                data = json.load(f)
            
            self.file_history = data.get('file_history', {})
            version_index = data.get('version_index', [])
            
            # Load each version
            for version_id in version_index:
                version_file = self.storage_dir / f"{version_id}.json"
                if version_file.exists():
                    with open(version_file, 'r') as f:
                        version_data = json.load(f)
                    self.versions[version_id] = Version.from_dict(version_data)
        
        except Exception as e:
            print(f"⚠️ Error loading version data: {e}")