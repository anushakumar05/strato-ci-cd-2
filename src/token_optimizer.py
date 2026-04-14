# src/token_optimizer.py
"""
Token Optimization System

Reduces Gemini API token usage through:
1. Smart context caching
2. Summary compression
3. Selective context loading
4. Response caching
5. Batch operations
"""

import hashlib
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta


class TokenOptimizer:
    """Manages token usage optimization strategies"""
    
    def __init__(self, cache_dir: str = ".token_cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        
        # Cache settings
        self.enable_response_cache = True
        self.cache_ttl_hours = 24
        
        # Context settings
        self.max_context_chars = 15000  # Limit context size
        self.use_compressed_summaries = True
        
        # Statistics
        self.stats = {
            'cache_hits': 0,
            'cache_misses': 0,
            'tokens_saved': 0,
            'api_calls_saved': 0
        }
    
    def get_compressed_context(self, full_context: str, relevance_keywords: list = None) -> str:
        """
        Compress context to only relevant parts
        
        Args:
            full_context: Full README/summary text
            relevance_keywords: Keywords to prioritize (optional)
            
        Returns:
            Compressed context string
        """
        if not full_context or len(full_context) < self.max_context_chars:
            return full_context
        
        lines = full_context.split('\n')
        
        # If we have keywords, prioritize relevant sections
        if relevance_keywords:
            scored_lines = []
            for i, line in enumerate(lines):
                score = sum(1 for kw in relevance_keywords if kw.lower() in line.lower())
                scored_lines.append((score, i, line))
            
            # Sort by score, keep high-scoring lines
            scored_lines.sort(reverse=True)
            
            # Take top 60% of lines by relevance
            keep_count = int(len(lines) * 0.6)
            kept_indices = sorted([idx for _, idx, _ in scored_lines[:keep_count]])
            compressed = '\n'.join(lines[i] for i in kept_indices)
        else:
            # Just truncate to max size
            char_count = 0
            kept_lines = []
            for line in lines:
                if char_count + len(line) > self.max_context_chars:
                    break
                kept_lines.append(line)
                char_count += len(line)
            compressed = '\n'.join(kept_lines)
        
        if len(compressed) < len(full_context):
            # Add note about compression
            saved_chars = len(full_context) - len(compressed)
            self.stats['tokens_saved'] += saved_chars // 4  # Rough token estimate
            compressed += f"\n\n[Note: Context compressed to save tokens. {saved_chars} chars removed]"
        
        return compressed
    
    def get_minimal_context(self, task_type: str) -> str:
        """
        Get minimal context based on task type
        
        Args:
            task_type: 'create', 'edit', 'review', 'summarize'
            
        Returns:
            Minimal context hint
        """
        minimal_contexts = {
            'create': "Create clean, well-documented Python code following PEP 8.",
            'edit': "Modify the existing code as requested while maintaining code quality.",
            'review': "Review code for security, performance, and quality issues.",
            'summarize': "Provide a concise technical summary."
        }
        
        return minimal_contexts.get(task_type, "")
    
    def cache_response(self, prompt_hash: str, response: str, metadata: dict = None):
        """Cache a Gemini response"""
        if not self.enable_response_cache:
            return
        
        cache_file = self.cache_dir / f"{prompt_hash}.json"
        
        cache_data = {
            'response': response,
            'timestamp': datetime.now().isoformat(),
            'metadata': metadata or {}
        }
        
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f)
    
    def get_cached_response(self, prompt: str) -> Optional[str]:
        """
        Try to get cached response
        
        Args:
            prompt: The prompt to look up
            
        Returns:
            Cached response or None
        """
        if not self.enable_response_cache:
            return None
        
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]
        cache_file = self.cache_dir / f"{prompt_hash}.json"
        
        if not cache_file.exists():
            self.stats['cache_misses'] += 1
            return None
        
        try:
            with open(cache_file, 'r') as f:
                cache_data = json.load(f)
            
            # Check if cache is still valid
            cached_time = datetime.fromisoformat(cache_data['timestamp'])
            if datetime.now() - cached_time > timedelta(hours=self.cache_ttl_hours):
                # Cache expired
                cache_file.unlink()
                self.stats['cache_misses'] += 1
                return None
            
            # Cache hit!
            self.stats['cache_hits'] += 1
            self.stats['api_calls_saved'] += 1
            print(f"Using cached response (saved API call)")
            return cache_data['response']
        
        except Exception as e:
            print(f"Cache read error: {e}")
            self.stats['cache_misses'] += 1
            return None
    
    def should_skip_context(self, task_type: str, code_length: int) -> bool:
        """
        Determine if we can skip loading full context
        
        Args:
            task_type: Type of task
            code_length: Length of code being processed
            
        Returns:
            True if context can be skipped
        """
        # For very simple tasks, skip context
        if task_type == 'review' and code_length < 100:
            return True
        
        if task_type == 'edit' and code_length < 50:
            return True
        
        return False
    
    def estimate_tokens(self, text: str) -> int:
        """
        Rough token estimation (1 token ≈ 4 chars for English)
        
        Args:
            text: Text to estimate
            
        Returns:
            Estimated token count
        """
        return len(text) // 4
    
    def get_stats(self) -> Dict[str, Any]:
        """Get optimization statistics"""
        total_calls = self.stats['cache_hits'] + self.stats['cache_misses']
        cache_rate = (self.stats['cache_hits'] / total_calls * 100) if total_calls > 0 else 0
        
        return {
            **self.stats,
            'cache_hit_rate': f"{cache_rate:.1f}%",
            'total_lookups': total_calls
        }
    
    def clear_cache(self):
        """Clear all cached responses"""
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
        print("🗑️  Cache cleared")


# Global optimizer instance
_optimizer = None

def get_optimizer() -> TokenOptimizer:
    """Get or create global optimizer instance"""
    global _optimizer
    if _optimizer is None:
        _optimizer = TokenOptimizer()
    return _optimizer


# Configuration presets
TOKEN_SAVING_PRESETS = {
    'aggressive': {
        'max_context_chars': 5000,
        'cache_ttl_hours': 72,
        'use_minimal_context': True,
        'skip_context_for_simple_tasks': True
    },
    'balanced': {
        'max_context_chars': 15000,
        'cache_ttl_hours': 24,
        'use_minimal_context': False,
        'skip_context_for_simple_tasks': True
    },
    'quality_first': {
        'max_context_chars': 50000,
        'cache_ttl_hours': 12,
        'use_minimal_context': False,
        'skip_context_for_simple_tasks': False
    }
}


def apply_preset(preset_name: str):
    """Apply a token saving preset"""
    optimizer = get_optimizer()
    preset = TOKEN_SAVING_PRESETS.get(preset_name, TOKEN_SAVING_PRESETS['balanced'])
    
    optimizer.max_context_chars = preset['max_context_chars']
    optimizer.cache_ttl_hours = preset['cache_ttl_hours']
    
    print(f"Applied '{preset_name}' token optimization preset")
    print(f"   Max context: {preset['max_context_chars']} chars")
    print(f"   Cache TTL: {preset['cache_ttl_hours']} hours")