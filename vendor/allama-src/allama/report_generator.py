"""
Moduł do generowania raportów z testów modeli LLM.
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader

import logging

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Klasa do generowania raportów z testów modeli LLM."""

    def __init__(self, config: Dict[str, Any]):
        """
        Inicjalizuje generator raportów.

        Args:
            config: Konfiguracja raportu
        """
        self.config = config
        self.report_config = config.get('report_config', {})
        self.colors = config.get('colors', {
            'light': '#f5f5f5',
            'dark': '#333',
            'primary': '#007bff',
            'success': '#28a745',
            'error': '#dc3545',
            'warning': '#ffc107'
        })
        
        # Inicjalizacja środowiska Jinja2
        templates_dir = os.path.join(os.path.dirname(__file__), 'templates')
        self.env = Environment(loader=FileSystemLoader(templates_dir))

    def generate_benchmark_report(self, report, output_file):
        """Render native benchmark evidence with escaped model output, offline."""
        from pathlib import Path
        environment = self.env.overlay(autoescape=True)
        content = environment.get_template('benchmark.html').render(report=report)
        target = Path(output_file)
        temporary = target.with_suffix('.html.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(target)

    def save_results_to_json(self, results: List[Dict[str, Any]], output_file: str = 'allama.json') -> None:
        """
        Zapisuje wyniki testów do pliku JSON.

        Args:
            results: Lista wyników testów
            output_file: Nazwa pliku wyjściowego
        """
        if not results:
            logger.error("Brak wyników do zapisania do JSON")
            return
        
        # Utwórz folder dla danych, jeśli nie istnieje
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = os.path.join(os.path.dirname(os.path.abspath(output_file)), "data")
        test_dir = os.path.join(data_dir, f"test_{timestamp}")
        
        try:
            os.makedirs(test_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Nie można utworzyć katalogu dla danych: {e}")
            # Kontynuuj z zapisem do głównego katalogu
            test_dir = os.path.dirname(os.path.abspath(output_file))
        
        # Zbierz informacje o promptach
        prompts_info = {}
        for result in results:
            prompt_name = result.get('prompt_name', 'Unknown')
            if prompt_name not in prompts_info:
                prompts_info[prompt_name] = {
                    'prompt_text': result.get('prompt', ''),
                    'description': result.get('prompt_description', ''),
                    'expected_keywords': result.get('expected_keywords', [])
                }
        
        # Przygotuj dane do zapisania
        export_data = {
            'timestamp': datetime.now().isoformat(),
            'models_tested': list(set(r['model_name'] for r in results)),
            'total_tests': len(results),
            'successful_tests': sum(1 for r in results if r['success']),
            'prompts_info': prompts_info,
            'results': results
        }
        
        # Zapisz do głównego pliku JSON
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Wyniki zapisane do pliku JSON: {output_file}")
        except Exception as e:
            logger.error(f"Błąd podczas zapisywania wyników do JSON: {e}")
        
        # Zapisz kopię w katalogu z danymi
        test_json_file = os.path.join(test_dir, "allama.json")
        try:
            with open(test_json_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Kopia wyników zapisana w katalogu danych: {test_json_file}")
            
            # Zapisz również informacje o promptach w osobnym pliku dla lepszej czytelności
            prompts_file = os.path.join(test_dir, "prompts.json")
            with open(prompts_file, 'w', encoding='utf-8') as f:
                json.dump(prompts_info, f, indent=2, ensure_ascii=False)
            
            return test_dir
        except Exception as e:
            logger.error(f"Błąd podczas zapisywania kopii wyników: {e}")
            return None

    def _calculate_statistics(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Oblicza statystyki na podstawie wyników testów.

        Args:
            results: Lista wyników testów

        Returns:
            Słownik ze statystykami
        """
        successful_tests = sum(1 for r in results if r['success'])
        models = set(r['model_name'] for r in results)

        # Oblicz średni czas odpowiedzi
        response_times = [r.get('response_time', 0) for r in results if r['success']]
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0

        # Oblicz wyniki dla każdego modelu
        model_scores = {}
        for model in models:
            model_results = [r for r in results if r['model_name'] == model and r['success']]
            if model_results:
                scores = []
                for result in model_results:
                    if 'evaluation' in result:
                        eval_data = result['evaluation']
                        score = self._calculate_score(eval_data)
                        scores.append(score)

                model_scores[model] = sum(scores) / len(scores) if scores else 0

        return {
            'models': models,
            'successful_tests': successful_tests,
            'success_rate': (successful_tests / len(results) * 100) if results else 0,
            'avg_response_time': avg_response_time,
            'model_scores': model_scores
        }

    def _calculate_score(self, evaluation: Dict[str, Any]) -> float:
        """
        Oblicza wynik na podstawie ewaluacji.

        Args:
            evaluation: Słownik z wynikami ewaluacji

        Returns:
            Wynik jako liczba zmiennoprzecinkowa
        """
        weights = self.config.get('evaluation_weights', {
            'correctness': 0.4,
            'efficiency': 0.2,
            'robustness': 0.2,
            'maintainability': 0.2
        })
        
        score = 0.0
        for key, weight in weights.items():
            if key in evaluation:
                score += evaluation[key] * weight
        
        return score

    def _generate_ranking_table(self, stats: Dict[str, Any]) -> str:
        """
        Generuje tabelę rankingową modeli.

        Args:
            stats: Statystyki z testów

        Returns:
            HTML tabeli rankingowej
        """
        model_scores = stats.get('model_scores', {})
        if not model_scores:
            return "<p>Brak danych do wygenerowania rankingu.</p>"
        
        # Sortuj modele według wyniku
        sorted_models = sorted(model_scores.items(), key=lambda x: x[1], reverse=True)
        
        html = """
        <table>
            <thead>
                <tr>
                    <th>Pozycja</th>
                    <th>Model</th>
                    <th>Wynik</th>
                </tr>
            </thead>
            <tbody>
        """
        
        for i, (model, score) in enumerate(sorted_models, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else ""
            html += f"""
                <tr>
                    <td>{i} {medal}</td>
                    <td>{model}</td>
                    <td class="score">{score:.2f}</td>
                </tr>
            """
        
        html += """
            </tbody>
        </table>
        """
        return html

    def _generate_model_section(self, model_name: str, results: List[Dict[str, Any]]) -> str:
        """
        Generuje sekcję HTML dla danego modelu.

        Args:
            model_name: Nazwa modelu
            results: Lista wyników dla danego modelu

        Returns:
            HTML sekcji modelu
        """
        success_count = sum(1 for r in results if r['success'])
        success_rate = (success_count / len(results) * 100) if results else 0
        
        html = f"""
        <div class="model-results">
            <div class="model-header">
                <h3>{model_name}</h3>
                <p>Testy zakończone sukcesem: {success_count}/{len(results)} ({success_rate:.1f}%)</p>
            </div>
        """
        
        for result in results:
            prompt_name = result.get('prompt_name', 'Brak nazwy')
            success = result.get('success', False)
            status_class = "success" if success else "error"
            status_text = "✅ Sukces" if success else "❌ Błąd"
            
            html += f"""
            <div class="prompt-result">
                <h4>{prompt_name}</h4>
                <p class="{status_class}">{status_text}</p>
            """
            
            if success:
                # Pokaż kod i ewaluację
                code = result.get('extracted_code', '')
                evaluation = result.get('evaluation', {})
                
                html += f"""
                <h5>Wygenerowany kod:</h5>
                <pre class="code-block">{code}</pre>
                
                <h5>Ewaluacja:</h5>
                <ul>
                """
                
                for key, value in evaluation.items():
                    if isinstance(value, (int, float)):
                        html += f"<li><strong>{key}:</strong> {value:.2f}</li>"
                    else:
                        html += f"<li><strong>{key}:</strong> {value}</li>"
                
                html += "</ul>"
                
                # Pokaż czas odpowiedzi
                response_time = result.get('response_time', 0)
                html += f"<p><strong>Czas odpowiedzi:</strong> {response_time:.2f}s</p>"
            else:
                # Pokaż błąd
                error = result.get('error', 'Nieznany błąd')
                html += f"""
                <h5>Błąd:</h5>
                <pre class="code-block error">{error}</pre>
                """
            
            html += "</div>"
        
        html += "</div>"
        return html

    def generate_html_report(self, results: List[Dict[str, Any]], 
                            output_file: str = 'allama.html',
                            json_file: str = 'allama.json') -> None:
        """
        Generuje raport HTML z wyników testów.

        Args:
            results: Lista wyników testów
            output_file: Nazwa pliku HTML
            json_file: Nazwa pliku JSON z wynikami
        """
        if not results:
            logger.error("Brak wyników do wygenerowania raportu")
            return

        # Zapisz wyniki do pliku JSON i uzyskaj ścieżkę do katalogu danych
        test_dir = self.save_results_to_json(results, json_file)
        
        # Oblicz statystyki
        stats = self._calculate_statistics(results)
        
        # Przygotuj dane do szablonu
        template = self.env.get_template('report_template.html')
        
        # Grupuj wyniki według modeli
        models_results = {}
        for result in results:
            model_name = result['model_name']
            if model_name not in models_results:
                models_results[model_name] = []
            models_results[model_name].append(result)
        
        # Generuj sekcje dla każdego modelu
        model_sections = ""
        for model_name, model_results in models_results.items():
            model_sections += self._generate_model_section(model_name, model_results)
        
        # Zbierz informacje o promptach
        prompts_info = {}
        for result in results:
            prompt_name = result.get('prompt_name', 'Unknown')
            if prompt_name not in prompts_info:
                prompts_info[prompt_name] = {
                    'prompt_text': result.get('prompt', ''),
                    'description': result.get('prompt_description', ''),
                    'expected_keywords': result.get('expected_keywords', [])
                }
        
        # Przygotuj dane JSON do osadzenia w HTML
        export_data = {
            'timestamp': datetime.now().isoformat(),
            'models_tested': list(set(r['model_name'] for r in results)),
            'total_tests': len(results),
            'successful_tests': sum(1 for r in results if r['success']),
            'prompts_info': prompts_info,
            'results': results
        }
        
        # Renderuj szablon
        html_content = template.render(
            title=self.report_config.get('title', 'Raport Testowania Modeli LLM'),
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            models_count=len(stats['models']),
            tests_count=len(results),
            successful_tests=stats['successful_tests'],
            success_rate=f"{stats['success_rate']:.1f}",
            avg_response_time=f"{stats['avg_response_time']:.2f}",
            ranking_table=self._generate_ranking_table(stats),
            model_sections=model_sections,
            colors=self.colors,
            test_results_json=json.dumps(export_data),
            prompts_info=prompts_info
        )

        # Zapisz raport HTML w głównym katalogu
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"Raport HTML zapisany do {output_file}")
        except Exception as e:
            logger.error(f"Błąd podczas zapisywania raportu: {e}")
            
        # Jeśli mamy katalog danych, zapisz również tam kopię raportu
        if test_dir:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            test_html_file = os.path.join(test_dir, f"allama.html")
            try:
                with open(test_html_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                logger.info(f"Kopia raportu HTML zapisana w katalogu danych: {test_html_file}")
                return test_html_file
            except Exception as e:
                logger.error(f"Błąd podczas zapisywania kopii raportu HTML: {e}")
                
        return output_file
