import pytest
from execution.static_validator import StaticValidator


class TestStaticValidation:

    def setup_method(self):
        self.validator = StaticValidator()

    def test_valid_python(self):
        files = [{'path': 'main.py', 'content': 'print("hello")'}]
        result = self.validator.validate('test-project', files)
        assert result.passed

    def test_syntax_error(self):
        files = [{'path': 'bad.py', 'content': 'def f(\n  print("bad")'}]
        result = self.validator.validate('test-project', files)
        assert not result.passed
        assert any('Syntax error' in e for e in result.errors)

    def test_valid_json(self):
        files = [{'path': 'config.json', 'content': '{"key": "value"}'}]
        result = self.validator.validate('test-project', files)
        assert result.passed

    def test_invalid_json(self):
        files = [{'path': 'bad.json', 'content': '{key: value}'}]
        result = self.validator.validate('test-project', files)
        assert not result.passed
        assert any('JSON' in e for e in result.errors)

    def test_duplicate_paths(self):
        files = [
            {'path': 'main.py', 'content': 'print(1)'},
            {'path': 'main.py', 'content': 'print(2)'},
        ]
        result = self.validator.validate('test-project', files)
        assert not result.passed
        assert any('Duplicate' in e for e in result.errors)

    def test_security_warning_eval(self):
        files = [{'path': 'dangerous.py', 'content': 'eval(input())'}]
        result = self.validator.validate('test-project', files)
        assert any('eval' in w for w in result.warnings)

    def test_security_warning_hardcoded_secret(self):
        files = [{'path': 'secrets.py', 'content': 'api_key = "abcdefghijklmnop123456"'}]
        result = self.validator.validate('test-project', files)
        assert any('secret' in w.lower() for w in result.warnings)

    def test_empty_project(self):
        result = self.validator.validate('test-project', [])
        assert result.passed  # No errors

    def test_html_missing_doctype(self):
        files = [{'path': 'index.html', 'content': '<div>hello</div>'}]
        result = self.validator.validate('test-project', files)
        assert any('html' in w.lower() for w in result.warnings)