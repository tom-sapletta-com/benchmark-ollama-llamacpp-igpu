"""
Moduł do ewaluacji wygenerowanego kodu.
"""
import ast
import os
import subprocess
import tempfile
from typing import Dict, Any, Tuple

class CodeEvaluator:
    """Klasa do oceny wygenerowanego kodu"""

    def __init__(self):
        self.metrics = {
            'syntax_valid': 0,
            'runs_without_error': 0,
            'has_function_def': 0,
            'has_docstring': 0,
            'has_error_handling': 0,
            'imports_used': 0,
            'line_count': 0,
            'response_time': 0,
            'contains_expected_keywords': 0
        }

    def extract_python_code(self, response_text: str) -> str:
        """Wyciąga kod Python z odpowiedzi modelu"""
        # Szuka bloków kodu między ```python i ```
        if '```python' in response_text:
            start = response_text.find('```python') + 9
            end = response_text.find('```', start)
            if end != -1:
                return response_text[start:end].strip()

        # Szuka bloków kodu między ``` i ```
        if '```' in response_text:
            parts = response_text.split('```')
            for i, part in enumerate(parts):
                if i % 2 == 1:  # Nieparzysty indeks = kod
                    # Usuwa pierwszą linię jeśli zawiera nazwę języka
                    lines = part.strip().split('\n')
                    if lines and any(lang in lines[0].lower() for lang in ['python', 'py']):
                        return '\n'.join(lines[1:]).strip()
                    return part.strip()

        # Jeśli nie ma bloków kodu, zwraca całą odpowiedź
        return response_text.strip()

    def check_syntax(self, code: str) -> bool:
        """Sprawdza poprawność składni kodu Python"""
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    def check_execution(self, code: str) -> Tuple[bool, str]:
        """Sprawdza czy kod można wykonać bez błędów"""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name

            # Wykonuje kod w subprocesie
            result = subprocess.run(
                ['python3', temp_file],  # Używamy python3 zamiast python
                capture_output=True,
                text=True,
                timeout=10
            )

            os.unlink(temp_file)

            if result.returncode == 0:
                return True, result.stdout
            else:
                return False, result.stderr

        except subprocess.TimeoutExpired:
            return False, "Timeout - kod wykonywał się zbyt długo"
        except Exception as e:
            return False, str(e)

    def analyze_code_quality(self, code: str) -> Dict[str, Any]:
        """Analizuje jakość kodu"""
        metrics = {}

        # Podstawowe metryki
        metrics['line_count'] = len([line for line in code.split('\n') if line.strip()])
        metrics['has_function_def'] = 'def ' in code
        metrics['has_class_def'] = 'class ' in code
        metrics['has_docstring'] = '"""' in code or "'''" in code
        metrics['has_comments'] = '#' in code
        metrics['has_error_handling'] = any(keyword in code for keyword in ['try:', 'except:', 'raise', 'assert'])
        metrics['imports_used'] = code.count('import ') + code.count('from ')

        return metrics

    def evaluate_code(self, code: str, prompt_data: Dict[str, Any], response_time: float) -> Dict[str, Any]:
        """Kompleksowa ocena wygenerowanego kodu"""
        results = {
            'code': code,
            'response_time': response_time,
            'syntax_valid': False,
            'runs_without_error': False,
            'execution_output': '',
            'quality_metrics': {}
        }

        # Sprawdź składnię
        results['syntax_valid'] = self.check_syntax(code)

        # Sprawdź wykonanie
        if results['syntax_valid']:
            can_run, output = self.check_execution(code)
            results['runs_without_error'] = can_run
            results['execution_output'] = output

        # Analiza jakości
        results['quality_metrics'] = self.analyze_code_quality(code)

        # Sprawdź czy kod zawiera oczekiwane słowa kluczowe z promptu
        expected_keywords = prompt_data.get('expected_keywords', [])
        code_lower = code.lower()

        found_keywords = [kw.lower() for kw in expected_keywords if kw.lower() in code_lower]

        results['contains_expected_keywords'] = len(found_keywords) > 0 if expected_keywords else True
        results['keyword_match_ratio'] = len(found_keywords) / len(expected_keywords) if expected_keywords else 1.0
        results['found_keywords'] = found_keywords
        results['expected_keywords'] = expected_keywords

        return results
