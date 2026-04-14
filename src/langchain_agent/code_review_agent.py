# src/langchain_agent/code_review_agent.py
"""
Enhanced Code Review Agent - Integrates with CI/CD

Improvements:
1. Automatic review on PR creation
2. Security vulnerability detection
3. Performance analysis
4. Best practices validation
5. Suggestions with code examples
6. Integration with GitHub Actions
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import re

from src.gemini_manager import _call_gemini_raw


class Severity(Enum):
    """Issue severity levels"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class ReviewIssue:
    """A code review issue"""
    severity: Severity
    category: str  # 'security', 'performance', 'style', 'bug', 'best-practice'
    file_path: str
    line_number: Optional[int]
    message: str
    suggestion: Optional[str] = None
    code_example: Optional[str] = None


class CodeReviewAgentV2:
    """
    Enhanced code review agent with multi-level analysis.
    """
    
    def __init__(self):
        self.issues: List[ReviewIssue] = []
    
    def review_code(
        self, 
        file_path: str, 
        code: str,
        context: str = ""
    ) -> Dict:
        """
        Comprehensive code review.
        
        Args:
            file_path: Path to the file being reviewed
            code: The code content
            context: Repository context for better analysis
        
        Returns:
            Dict with review results
        """
        self.issues = []
        
        # Run multiple analysis passes
        self._check_security(file_path, code)
        self._check_performance(file_path, code)
        self._check_best_practices(file_path, code)
        self._check_bugs(file_path, code)
        
        # AI-powered deep review
        ai_issues = self._ai_review(file_path, code, context)
        self.issues.extend(ai_issues)
        
        return self._format_results()
    
    # ========================================================================
    # Static Analysis Checks
    # ========================================================================
    
    def _check_security(self, file_path: str, code: str):
        """Check for security vulnerabilities"""
        
        # Check 1: Hardcoded secrets
        secret_patterns = [
            (r'password\s*=\s*["\'][^"\']+["\']', 'Hardcoded password detected'),
            (r'api[_-]?key\s*=\s*["\'][^"\']+["\']', 'Hardcoded API key detected'),
            (r'secret\s*=\s*["\'][^"\']+["\']', 'Hardcoded secret detected'),
            (r'token\s*=\s*["\'][^"\']+["\']', 'Hardcoded token detected'),
        ]
        
        for pattern, message in secret_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                self.issues.append(ReviewIssue(
                    severity=Severity.CRITICAL,
                    category='security',
                    file_path=file_path,
                    line_number=None,
                    message=message,
                    suggestion='Use environment variables: os.getenv("API_KEY")'
                ))
        
        # Check 2: SQL injection risk
        if re.search(r'execute\([^)]*f["\']|\.format\(', code):
            if 'cursor' in code or 'execute' in code:
                self.issues.append(ReviewIssue(
                    severity=Severity.HIGH,
                    category='security',
                    file_path=file_path,
                    line_number=None,
                    message='Potential SQL injection - string formatting in SQL query',
                    suggestion='Use parameterized queries: cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))',
                    code_example='# Bad:\ncursor.execute(f"SELECT * FROM users WHERE id = {user_id}")\n\n# Good:\ncursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))'
                ))
        
        # Check 3: Insecure random
        if 'random.random()' in code or 'random.randint' in code:
            if 'password' in code or 'token' in code or 'secret' in code:
                self.issues.append(ReviewIssue(
                    severity=Severity.MEDIUM,
                    category='security',
                    file_path=file_path,
                    line_number=None,
                    message='Using insecure random for security-sensitive data',
                    suggestion='Use secrets module: secrets.token_urlsafe(32)'
                ))
        
        # Check 4: eval() or exec()
        if re.search(r'\beval\(|\bexec\(', code):
            self.issues.append(ReviewIssue(
                severity=Severity.CRITICAL,
                category='security',
                file_path=file_path,
                line_number=None,
                message='Use of eval() or exec() is dangerous',
                suggestion='Avoid eval/exec. Use ast.literal_eval() for safe evaluation.'
            ))
    
    def _check_performance(self, file_path: str, code: str):
        """Check for performance issues"""
        
        # Check 1: Inefficient loops
        if re.search(r'for.*in.*range\(len\(', code):
            self.issues.append(ReviewIssue(
                severity=Severity.LOW,
                category='performance',
                file_path=file_path,
                line_number=None,
                message='Inefficient loop pattern',
                suggestion='Use enumerate() instead: for i, item in enumerate(items)',
                code_example='# Bad:\nfor i in range(len(items)):\n    print(items[i])\n\n# Good:\nfor i, item in enumerate(items):\n    print(item)'
            ))
        
        # Check 2: List comprehension vs append
        lines = code.split('\n')
        for i, line in enumerate(lines):
            if 'for' in line and i + 1 < len(lines):
                if '.append(' in lines[i + 1]:
                    self.issues.append(ReviewIssue(
                        severity=Severity.LOW,
                        category='performance',
                        file_path=file_path,
                        line_number=i + 1,
                        message='Consider using list comprehension',
                        suggestion='More efficient: result = [item for item in items]'
                    ))
                    break
        
        # Check 3: String concatenation in loops
        if re.search(r'for.*:\s*.*\+=.*["\']', code):
            self.issues.append(ReviewIssue(
                severity=Severity.MEDIUM,
                category='performance',
                file_path=file_path,
                line_number=None,
                message='String concatenation in loop is inefficient',
                suggestion='Use join(): "".join(items) or use list and join at end'
            ))
    
    def _check_best_practices(self, file_path: str, code: str):
        """Check Python best practices"""
        
        # Check 1: Missing docstrings
        if re.search(r'^def\s+\w+\(', code, re.MULTILINE):
            # Function exists
            if not re.search(r'"""|\'\'\'', code):
                self.issues.append(ReviewIssue(
                    severity=Severity.LOW,
                    category='best-practice',
                    file_path=file_path,
                    line_number=None,
                    message='Functions should have docstrings',
                    suggestion='Add docstrings to document function purpose, args, and return values'
                ))
        
        # Check 2: Bare except
        if re.search(r'except\s*:', code):
            self.issues.append(ReviewIssue(
                severity=Severity.MEDIUM,
                category='best-practice',
                file_path=file_path,
                line_number=None,
                message='Bare except clause - too broad',
                suggestion='Catch specific exceptions: except ValueError, TypeError:',
                code_example='# Bad:\ntry:\n    risky_operation()\nexcept:\n    pass\n\n# Good:\ntry:\n    risky_operation()\nexcept (ValueError, TypeError) as e:\n    logger.error(f"Error: {e}")'
            ))
        
        # Check 3: Mutable default arguments
        if re.search(r'def\s+\w+\([^)]*=\s*\[|def\s+\w+\([^)]*=\s*\{', code):
            self.issues.append(ReviewIssue(
                severity=Severity.HIGH,
                category='best-practice',
                file_path=file_path,
                line_number=None,
                message='Mutable default argument (list or dict)',
                suggestion='Use None as default: def func(items=None): items = items or []',
                code_example='# Bad:\ndef append_to(item, list=[]):\n    list.append(item)\n    return list\n\n# Good:\ndef append_to(item, list=None):\n    if list is None:\n        list = []\n    list.append(item)\n    return list'
            ))
    
    def _check_bugs(self, file_path: str, code: str):
        """Check for common bugs"""
        
        # Check 1: Comparison to True/False
        if re.search(r'==\s*True|==\s*False|is\s*True|is\s*False', code):
            self.issues.append(ReviewIssue(
                severity=Severity.LOW,
                category='bug',
                file_path=file_path,
                line_number=None,
                message='Comparing to True/False is redundant',
                suggestion='Use direct boolean check: if condition: instead of if condition == True:'
            ))
        
        # Check 2: Missing return statement
        lines = code.split('\n')
        in_function = False
        has_return = False
        
        for line in lines:
            if re.match(r'^\s*def\s+\w+', line):
                in_function = True
                has_return = False
            elif in_function and 'return' in line:
                has_return = True
            elif in_function and re.match(r'^\S', line):  # New function or end
                if not has_return and 'def ' in lines[lines.index(line) - 10:lines.index(line)]:
                    # Function ended without return
                    pass  # Too many false positives
                in_function = False
    
    # ========================================================================
    # AI-Powered Review
    # ========================================================================
    
    def _ai_review(
        self, 
        file_path: str, 
        code: str, 
        context: str
    ) -> List[ReviewIssue]:
        """Use Gemini for deep code review"""
        
        review_prompt = f"""
You are a senior software engineer reviewing code.

FILE: {file_path}

REPOSITORY CONTEXT:
{context[:500] if context else 'No context provided'}

CODE TO REVIEW:
```python
{code}
```

Perform a comprehensive code review focusing on:
1. Logic errors or bugs
2. Edge cases not handled
3. Architecture improvements
4. Readability issues
5. Missing error handling

Return your review as a JSON array of issues:
[
    {{
        "severity": "critical|high|medium|low|info",
        "category": "bug|security|performance|style|best-practice",
        "line_number": 10,
        "message": "Brief description of the issue",
        "suggestion": "How to fix it",
        "code_example": "# Example of better code (optional)"
    }}
]

Focus on actionable feedback. Limit to top 5 most important issues.
Return ONLY the JSON array, no markdown.
"""
        
        try:
            response = _call_gemini_raw(review_prompt)
            
            # Extract JSON
            import json
            json_match = re.search(r'\[.*\]', response, re.DOTALL)
            if json_match:
                issues_data = json.loads(json_match.group())
                
                issues = []
                for issue_data in issues_data[:5]:  # Limit to 5
                    try:
                        issues.append(ReviewIssue(
                            severity=Severity(issue_data.get('severity', 'info')),
                            category=issue_data.get('category', 'best-practice'),
                            file_path=file_path,
                            line_number=issue_data.get('line_number'),
                            message=issue_data.get('message', ''),
                            suggestion=issue_data.get('suggestion'),
                            code_example=issue_data.get('code_example')
                        ))
                    except:
                        continue
                
                return issues
            
        except Exception as e:
            print(f"⚠️  AI review failed: {e}")
        
        return []
    
    # ========================================================================
    # Results Formatting
    # ========================================================================
    
    def _format_results(self) -> Dict:
        """Format review results"""
        
        # Group by severity
        by_severity = {
            'critical': [],
            'high': [],
            'medium': [],
            'low': [],
            'info': []
        }
        
        for issue in self.issues:
            by_severity[issue.severity.value].append(issue)
        
        # Calculate score (100 - penalty points)
        score = 100
        score -= len(by_severity['critical']) * 20
        score -= len(by_severity['high']) * 10
        score -= len(by_severity['medium']) * 5
        score -= len(by_severity['low']) * 2
        score = max(0, score)
        
        return {
            'score': score,
            'total_issues': len(self.issues),
            'by_severity': {
                k: len(v) for k, v in by_severity.items()
            },
            'issues': [
                {
                    'severity': issue.severity.value,
                    'category': issue.category,
                    'file': issue.file_path,
                    'line': issue.line_number,
                    'message': issue.message,
                    'suggestion': issue.suggestion,
                    'example': issue.code_example
                }
                for issue in self.issues
            ],
            'passed': score >= 70
        }
    
    def generate_report(self) -> str:
        """Generate human-readable review report"""
        results = self._format_results()
        
        report = []
        report.append("="*60)
        report.append("CODE REVIEW REPORT")
        report.append("="*60)
        report.append(f"\nScore: {results['score']}/100")
        report.append(f"Status: {'✅ PASSED' if results['passed'] else '❌ NEEDS WORK'}\n")
        
        report.append(f"Total Issues: {results['total_issues']}")
        report.append(f"  🔴 Critical: {results['by_severity']['critical']}")
        report.append(f"  🟠 High: {results['by_severity']['high']}")
        report.append(f"  🟡 Medium: {results['by_severity']['medium']}")
        report.append(f"  🟢 Low: {results['by_severity']['low']}")
        report.append(f"  ℹ️  Info: {results['by_severity']['info']}\n")
        
        if self.issues:
            report.append("ISSUES FOUND:\n")
            
            for issue in sorted(self.issues, key=lambda x: x.severity.value):
                severity_emoji = {
                    'critical': '🔴',
                    'high': '🟠',
                    'medium': '🟡',
                    'low': '🟢',
                    'info': 'ℹ️'
                }
                
                report.append(f"{severity_emoji[issue.severity.value]} [{issue.severity.value.upper()}] {issue.category}")
                report.append(f"   File: {issue.file_path}")
                if issue.line_number:
                    report.append(f"   Line: {issue.line_number}")
                report.append(f"   Issue: {issue.message}")
                
                if issue.suggestion:
                    report.append(f"   💡 Fix: {issue.suggestion}")
                
                if issue.code_example:
                    report.append(f"   Example:\n{issue.code_example}")
                
                report.append("")
        else:
            report.append("✅ No issues found!\n")
        
        report.append("="*60)
        
        return "\n".join(report)


# ============================================================================
# Convenience Function
# ============================================================================

def review_file(file_path: str, code: str, context: str = "") -> Dict:
    """Quick code review"""
    reviewer = CodeReviewAgentV2()
    return reviewer.review_code(file_path, code, context)