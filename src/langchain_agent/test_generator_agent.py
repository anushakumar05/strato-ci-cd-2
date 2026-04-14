# src/langchain_agent/test_generator_agent.py
"""
Intelligent Test Generation Agent

Automatically generates comprehensive unit and integration tests for Python code.

Features:
1. Analyzes code structure and dependencies
2. Generates pytest test cases
3. Creates fixtures and mocks
4. Adds edge case tests
5. Generates docstring examples
6. Creates integration test templates

Usage:
    from src.test_generator_agent import TestGeneratorAgent
    
    agent = TestGeneratorAgent()
    tests = agent.generate_tests(
        file_path="src/my_module.py",
        code=code_content
    )
    
    # Save tests
    with open("tests/test_my_module.py", "w") as f:
        f.write(tests)
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import re
import ast

from src.gemini_manager import _call_gemini_raw, clean_gemini_code


@dataclass
class FunctionInfo:
    """Information about a function to test"""
    name: str
    args: List[str]
    returns: Optional[str]
    docstring: Optional[str]
    is_async: bool
    decorators: List[str]
    complexity: str  # 'simple', 'medium', 'complex'

class TestGeneratorAgent:
    """
    Intelligent test generation agent using AI and static analysis.
    """
    
    def __init__(self):
        self.test_coverage_target = 80  # Aim for 80% coverage
    
    # ========================================================================
    # Main Entry Point
    # ========================================================================
    
    def generate_tests(
        self, 
        file_path: str, 
        code: str,
        test_style: str = "pytest",  # 'pytest' or 'unittest'
        include_integration: bool = False
    ) -> str:
        """
        Generate comprehensive tests for a Python file.
        
        Args:
            file_path: Path to the file being tested
            code: The source code
            test_style: 'pytest' or 'unittest'
            include_integration: Also generate integration tests
        
        Returns:
            Complete test file as string
        """
        # Step 1: Analyze code structure
        functions = self._analyze_code(code)
        classes = self._analyze_classes(code)
        imports = self._extract_imports(code)
        
        if not functions and not classes:
            return self._generate_empty_test(file_path)
        
        # Step 2: Generate test structure
        test_code = self._generate_test_file_header(file_path, imports)
        
        # Step 3: Generate fixtures
        test_code += self._generate_fixtures(functions, classes, code)
        
        # Step 4: Generate function tests
        for func in functions:
            test_code += self._generate_function_tests(func, code, test_style, file_path)
        
        # Step 5: Generate class tests
        for cls in classes:
            test_code += self._generate_class_tests(cls, code, test_style)
        
        # Step 6: Generate integration tests (optional)
        if include_integration:
            test_code += self._generate_integration_tests(file_path, code)
        
        # Step 7: Add edge case tests
        test_code += self._generate_edge_case_tests(functions)
        
        return test_code
    
    # ========================================================================
    # Code Analysis
    # ========================================================================
    
    def _analyze_code(self, code: str) -> List[FunctionInfo]:
        """Extract function information using AST"""
        functions = []
        
        try:
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Skip private functions (start with _)
                    if node.name.startswith('_') and not node.name.startswith('__'):
                        continue
                    
                    # Extract function info
                    args = [arg.arg for arg in node.args.args]
                    
                    # Get return type annotation
                    returns = None
                    if node.returns:
                        returns = ast.unparse(node.returns)
                    
                    # Get docstring
                    docstring = ast.get_docstring(node)
                    
                    # Check if async
                    is_async = isinstance(node, ast.AsyncFunctionDef)
                    
                    # Get decorators
                    decorators = [ast.unparse(d) for d in node.decorator_list]
                    
                    # Estimate complexity
                    complexity = self._estimate_complexity(node)
                    
                    functions.append(FunctionInfo(
                        name=node.name,
                        args=args,
                        returns=returns,
                        docstring=docstring,
                        is_async=is_async,
                        decorators=decorators,
                        complexity=complexity
                    ))
        
        except SyntaxError:
            print("⚠️  Could not parse code with AST, using regex fallback")
            # Fallback to regex
            pattern = r'def\s+(\w+)\s*\(([^)]*)\)'
            matches = re.findall(pattern, code)
            
            for name, args_str in matches:
                if not name.startswith('_'):
                    args = [a.strip().split('=')[0].strip() for a in args_str.split(',') if a.strip()]
                    functions.append(FunctionInfo(
                        name=name,
                        args=args,
                        returns=None,
                        docstring=None,
                        is_async=False,
                        decorators=[],
                        complexity='medium'
                    ))
        
        return functions
    
    def _analyze_classes(self, code: str) -> List[Dict]:
        """Extract class information"""
        classes = []
        
        try:
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Skip private classes
                    if node.name.startswith('_'):
                        continue
                    
                    methods = []
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            methods.append(item.name)
                    
                    classes.append({
                        'name': node.name,
                        'methods': methods,
                        'bases': [ast.unparse(base) for base in node.bases]
                    })
        
        except SyntaxError:
            # Fallback to regex
            pattern = r'class\s+(\w+)'
            matches = re.findall(pattern, code)
            for name in matches:
                if not name.startswith('_'):
                    classes.append({
                        'name': name,
                        'methods': [],
                        'bases': []
                    })
        
        return classes
    
    def _extract_imports(self, code: str) -> List[str]:
        """Extract imports from code"""
        imports = []
        
        for line in code.split('\n'):
            line = line.strip()
            if line.startswith('import ') or line.startswith('from '):
                imports.append(line)
        
        return imports
    
    def _estimate_complexity(self, node: ast.FunctionDef) -> str:
        """Estimate function complexity"""
        # Count control flow statements
        control_flow = 0
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.Try)):
                control_flow += 1
        
        if control_flow == 0:
            return 'simple'
        elif control_flow <= 3:
            return 'medium'
        else:
            return 'complex'
    
    # ========================================================================
    def _generate_test_file_header(self, file_path: str, imports: List[str]) -> str:
        """Generate test file header with imports"""
        module_name = file_path.replace('/', '.').replace('.py', '')
        
        header = f'''"""
Tests for {file_path}

Auto-generated by TestGeneratorAgent
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from {module_name} import *

'''
        
        # Add relevant imports
        if any('datetime' in imp for imp in imports):
            header += "from datetime import datetime\n"
        
        if any('pathlib' in imp for imp in imports):
            header += "from pathlib import Path\n"
        
        header += "\n\n"
        
        return header
    
    def _generate_fixtures(
        self, 
        functions: List[FunctionInfo], 
        classes: List[Dict],
        code: str
    ) -> str:
        """Generate pytest fixtures"""
        fixtures = "# ============================================================================\n"
        fixtures += "# Fixtures\n"
        fixtures += "# ============================================================================\n\n"
        
        # Generate fixtures for classes
        for cls in classes:
            fixtures += f'''@pytest.fixture
def {cls['name'].lower()}_instance():
    """Fixture for {cls['name']} instance"""
    return {cls['name']}()


'''
        
        # Generate common data fixtures
        if any('file' in f.name.lower() or 'path' in f.name.lower() for f in functions):
            fixtures += '''@pytest.fixture
def temp_file(tmp_path):
    """Fixture for temporary test file"""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")
    return test_file


'''
        
        if any('db' in f.name.lower() or 'database' in f.name.lower() for f in functions):
            fixtures += '''@pytest.fixture
def mock_db():
    """Fixture for mock database"""
    db = Mock()
    db.query.return_value = []
    return db


'''
        
        return fixtures
    
    def _generate_function_tests(
        self, 
        func: FunctionInfo, 
        code: str,
        test_style: str,
        file_path: str = ""
    ) -> str:
        """Generate test cases for a function using AI"""
        
        # Use AI to generate comprehensive tests — include FULL source code
        # so Gemini can read actual error messages and logic
        test_prompt = f"""
Generate pytest test cases for the function `{func.name}` from this Python source file.

### FILE PATH: {file_path}
(This means imports should be like: `from {file_path.replace('/', '.').replace('.py', '')} import {func.name}`)

### FULL SOURCE CODE:
```python
{code}
```

### FUNCTION INFO:
- Name: {func.name}
- Arguments: {', '.join(func.args)}
- Returns: {func.returns or 'Unknown'}
- Docstring: {func.docstring or 'None'}

### RULES (MUST FOLLOW ALL):
1. Generate 3-5 test cases covering happy path, edge cases, and error cases.
2. Use pytest style with descriptive test names (plain functions, NOT unittest.TestCase classes).
3. For exception tests, use ONLY `with pytest.raises(ExceptionType):` — do NOT check the message.
   - Do NOT use `assertRaisesRegex`, `self.assertRaises`, or `match=` parameter.
4. For floating point comparisons, use `assert result == pytest.approx(expected)`.
5. INCLUDE the necessary import statements at the top (e.g. `from {file_path.replace('/', '.').replace('.py', '')} import {func.name}`).
6. Do NOT test GUI, tkinter, pygame, or any code that needs a display.
7. Do NOT use unittest.TestCase — write plain pytest functions.
8. Tests must run in HEADLESS CI — no user input, no file system assumptions, no display.
9. CRITICAL: DO NOT write tests for functions that call `input()`. They block headless CI and cause StopIteration errors. Only test pure logic/math functions. If the function requires `input()`, do not generate a test for it.
10. Do NOT mix `capsys` and `@patch('builtins.print')`. If you mock print, assert on `mock_print.call_args`. If you use `capsys`, do not mock print.
11. For SystemExit, remember `sys.exit()` defaults to code `None`. Use `assert excinfo.value.code in (None, 0)`.
"""
        
        try:
            ai_tests = _call_gemini_raw(test_prompt)
            ai_tests = clean_gemini_code(ai_tests)
            
            # Add section header
            tests = f"\n# ============================================================================\n"
            tests += f"# Tests for {func.name}()\n"
            tests += f"# ============================================================================\n\n"
            tests += ai_tests + "\n\n"
            
            return tests
            
        except Exception as e:
            print(f"⚠️  AI test generation failed for {func.name}, using template")
            return self._generate_template_tests(func)
    
    def _generate_template_tests(self, func: FunctionInfo) -> str:
        """Generate template tests when AI fails"""
        tests = f"\n# Tests for {func.name}()\n\n"
        
        tests += f'''def test_{func.name}_basic():
    """Test {func.name} with valid inputs"""
    # TODO: Add test implementation
    pass


def test_{func.name}_edge_cases():
    """Test {func.name} with edge cases"""
    # TODO: Add test implementation
    pass


def test_{func.name}_errors():
    """Test {func.name} error handling"""
    # TODO: Add test implementation
    pass


'''
        
        return tests
    
    def _generate_class_tests(
        self, 
        cls: Dict, 
        code: str,
        test_style: str
    ) -> str:
        """Generate test cases for a class"""
        tests = f"\n# ============================================================================\n"
        tests += f"# Tests for {cls['name']} class\n"
        tests += f"# ============================================================================\n\n"
        
        # Test class instantiation
        tests += f'''def test_{cls['name'].lower()}_instantiation():
    """Test {cls['name']} can be instantiated"""
    instance = {cls['name']}()
    assert instance is not None


'''
        
        # Test each method
        for method in cls['methods']:
            if not method.startswith('_'):
                tests += f'''def test_{cls['name'].lower()}_{method}({cls['name'].lower()}_instance):
    """Test {cls['name']}.{method}()"""
    # TODO: Add test implementation
    pass


'''
        
        return tests
    
    def _generate_edge_case_tests(self, functions: List[FunctionInfo]) -> str:
        """Generate tests for common edge cases"""
        tests = "\n# ============================================================================\n"
        tests += "# Edge Case Tests\n"
        tests += "# ============================================================================\n\n"
        
        # Check if any functions take string arguments
        string_funcs = [f for f in functions if any('str' in arg.lower() for arg in f.args)]
        if string_funcs:
            func = string_funcs[0]
            tests += f'''def test_{func.name}_empty_string():
    """Test {func.name} handles empty string"""
    # TODO: Add test for empty string input
    pass


'''
        
        # Check if any functions take list/dict arguments
        collection_funcs = [f for f in functions if any('list' in arg.lower() or 'dict' in arg.lower() for arg in f.args)]
        if collection_funcs:
            func = collection_funcs[0]
            tests += f'''def test_{func.name}_empty_collection():
    """Test {func.name} handles empty collections"""
    # TODO: Add test for empty list/dict
    pass


'''
        
        return tests
    
    def _generate_integration_tests(self, file_path: str, code: str) -> str:
        """Generate integration test template"""
        tests = "\n# ============================================================================\n"
        tests += "# Integration Tests\n"
        tests += "# ============================================================================\n\n"
        
        tests += '''@pytest.mark.integration
def test_integration_workflow():
    """Test complete workflow integration"""
    # TODO: Add integration test
    # This should test how multiple functions/classes work together
    pass


@pytest.mark.integration
def test_external_dependencies():
    """Test integration with external dependencies"""
    # TODO: Add tests for external API calls, database, etc.
    pass


'''
        
        return tests
    
    def _generate_empty_test(self, file_path: str) -> str:
        """Generate placeholder when no testable code found"""
        return f'''"""
Tests for {file_path}

No testable functions or classes found.
"""

import pytest

def test_placeholder():
    """Placeholder test"""
    assert True
'''
    
    # ========================================================================
    # Advanced Features
    # ========================================================================
    
    def generate_property_based_tests(
        self, 
        func: FunctionInfo, 
        code: str
    ) -> str:
        """Generate property-based tests using Hypothesis"""
        tests = f"\n# Property-based tests for {func.name}\n"
        tests += "from hypothesis import given, strategies as st\n\n"
        
        tests += f'''@given(st.integers(), st.text())
def test_{func.name}_property(arg1, arg2):
    """Property-based test for {func.name}"""
    # TODO: Define properties that should always hold
    pass


'''
        
        return tests
    
    def generate_parametrized_tests(
        self, 
        func: FunctionInfo,
        test_cases: List[Tuple]
    ) -> str:
        """Generate parametrized tests"""
        tests = f"\n@pytest.mark.parametrize('input,expected', [\n"
        
        for input_val, expected in test_cases:
            tests += f"    ({input_val}, {expected}),\n"
        
        tests += "])\n"
        tests += f"def test_{func.name}_parametrized(input, expected):\n"
        tests += f"    assert {func.name}(input) == expected\n\n"
        
        return tests
    
    def analyze_coverage_gaps(
        self, 
        source_file: str, 
        test_file: str
    ) -> Dict:
        """Analyze what's not covered by existing tests"""
        # This would integrate with coverage.py
        # Returns suggestions for missing tests
        return {
            'uncovered_functions': [],
            'uncovered_branches': [],
            'suggestions': []
        }


# ============================================================================
# Convenience Functions
# ============================================================================

def generate_tests_for_file(file_path: str) -> str:
    """
    Quick function to generate tests for a file.
    
    Usage:
        tests = generate_tests_for_file("src/my_module.py")
        with open("tests/test_my_module.py", "w") as f:
            f.write(tests)
    """
    with open(file_path, 'r') as f:
        code = f.read()
    
    agent = TestGeneratorAgent()
    return agent.generate_tests(file_path, code)


def generate_tests_for_function(func_name: str, code: str) -> str:
    """Generate tests for a specific function"""
    agent = TestGeneratorAgent()
    
    # Extract just that function
    # Then generate tests
    # Simplified for now
    
    return agent.generate_tests("module.py", code)


# ============================================================================
# CLI Interface
# ============================================================================

if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate tests for Python files")
    parser.add_argument("file", help="Python file to generate tests for")
    parser.add_argument("-o", "--output", help="Output test file path")
    parser.add_argument("-i", "--integration", action="store_true", help="Include integration tests")
    
    args = parser.parse_args()
    
    # Generate tests
    tests = generate_tests_for_file(args.file)
    
    # Save or print
    if args.output:
        with open(args.output, 'w') as f:
            f.write(tests)
        print(f"✅ Tests written to {args.output}")
    else:
        print(tests)