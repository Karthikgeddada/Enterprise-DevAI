import ast
import json
import os
import re
from typing import List, Dict, Any

from execution.base import BaseValidator, ValidationResult


class StaticValidator(BaseValidator):
    """Level A static validation - works without remote execution."""

    @property
    def level(self) -> str:
        return 'static'

    def validate(self, project_id: str, files: List[Dict[str, str]]) -> ValidationResult:
        result = ValidationResult(level='static', passed=True)

        py_files = [f for f in files if f.get('path', '').endswith('.py')]
        json_files = [f for f in files if f.get('path', '').endswith('.json')]
        html_files = [f for f in files if f.get('path', '').endswith('.html')]

        for f in py_files:
            path = f.get('path', '')
            content = f.get('content', '')
            check_result = self._check_python_syntax(path, content)
            result.add_check('python_syntax', check_result['passed'], check_result['message'], {'path': path})

        for f in json_files:
            path = f.get('path', '')
            content = f.get('content', '')
            check_result = self._check_json(path, content)
            result.add_check('json_validity', check_result['passed'], check_result['message'], {'path': path})

        for f in html_files:
            path = f.get('path', '')
            content = f.get('content', '')
            check_result = self._check_html(path, content)
            if not check_result['passed']:
                result.add_warning('html_check', check_result['message'])

        has_requirements = any(f.get('path') == 'requirements.txt' for f in files)
        if has_requirements:
            result.add_check('requirements_present', True, 'requirements.txt found')
        else:
            result.add_warning('requirements', 'No requirements.txt found')

        for f in py_files:
            path = f.get('path', '')
            content = f.get('content', '')
            sec_result = self._check_security_issues(path, content)
            if not sec_result['passed']:
                result.add_warning('security', sec_result['message'])

        paths = [f.get('path') for f in files if f.get('path')]
        duplicates = [p for p in paths if paths.count(p) > 1]
        if duplicates:
            result.add_check('patch_integrity', False, f"Duplicate paths: {set(duplicates)}")
        else:
            result.add_check('patch_integrity', True, 'No duplicate file paths')

        result.passed = len(result.errors) == 0
        passed_count = sum(1 for c in result.checks if c['passed'])
        result.summary = f"{passed_count}/{len(result.checks)} checks passed, {len(result.warnings)} warnings"
        return result

    def _check_python_syntax(self, path: str, content: str) -> Dict[str, Any]:
        try:
            ast.parse(content, filename=path)
            return {'passed': True, 'message': 'Syntax OK'}
        except SyntaxError as e:
            return {'passed': False, 'message': f'Syntax error at line {e.lineno}: {e.msg}'}

    def _check_json(self, path: str, content: str) -> Dict[str, Any]:
        if not content.strip():
            return {'passed': True, 'message': 'Empty JSON file'}
        try:
            json.loads(content)
            return {'passed': True, 'message': 'Valid JSON'}
        except json.JSONDecodeError as e:
            return {'passed': False, 'message': f'JSON parse error: {e}'}

    def _check_html(self, path: str, content: str) -> Dict[str, Any]:
        if '<html' not in content.lower() and '<!doctype' not in content.lower():
            return {'passed': False, 'message': 'Missing <html> or <!doctype> tag'}
        if '</html>' not in content.lower():
            return {'passed': False, 'message': 'Missing closing </html> tag'}
        return {'passed': True, 'message': 'HTML structure OK'}

    def _check_security_issues(self, path: str, content: str) -> Dict[str, Any]:
        issues = []
        if re.search(r'(api_key|secret|password|token)\s*=\s*["\'][a-zA-Z0-9]{10,}', content, re.IGNORECASE):
            issues.append('Possible hardcoded secret')
        if re.search(r'\beval\s*\(', content) or re.search(r'\bexec\s*\(', content):
            issues.append('eval()/exec() detected')
        if 'shell=True' in content:
            issues.append('shell=True in subprocess')
        if issues:
            return {'passed': False, 'message': '; '.join(issues)}
        return {'passed': True, 'message': 'No issues detected'}