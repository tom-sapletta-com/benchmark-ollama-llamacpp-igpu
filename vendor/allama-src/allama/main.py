#!/usr/bin/env python3
"""
TestLLM - System do testowania i porównywania modeli LLM w kontekście generowania kodu
"""

import os
import sys
import csv
import json
import time
import logging
import requests
import argparse
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime

from allama.evaluator import CodeEvaluator
from allama.config_loader import get_config, ensure_config_files_exist
from allama.report_generator import ReportGenerator
from allama.open_report import open_report_in_browser
from allama.publisher import ResultPublisher

# Konfiguracja loggera
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LLMTester:
    """Główna klasa do testowania modeli LLM"""

    def __init__(self, models_file: str = 'models.csv', config_path: str = None):
        self.config = get_config(config_path)
        self.models_file = models_file

        prompts_file_path = self.config.get('prompts_file', 'prompts.json')
        if not os.path.isabs(prompts_file_path):
            # Fix: Use dirname only twice to get the project root correctly
            project_root = os.path.dirname(os.path.dirname(__file__))
            self.prompts_file = os.path.join(project_root, prompts_file_path)
        else:
            self.prompts_file = prompts_file_path

        self.evaluator = CodeEvaluator()
        self.results = []
        self.test_prompts = self.load_prompts()

    def load_prompts(self) -> List[Dict[str, Any]]:
        """Ładuje prompty z pliku JSON"""
        try:
            with open(self.prompts_file, 'r', encoding='utf-8') as f:
                prompts = json.load(f)
                logger.info(f"Załadowano {len(prompts)} promptów z {self.prompts_file}")
                return prompts
        except FileNotFoundError:
            logger.error(f"Plik z promptami nie został znaleziony: {self.prompts_file}")
            return []
        except json.JSONDecodeError:
            logger.error(f"Błąd dekodowania pliku JSON: {self.prompts_file}")
            return []
        except Exception as e:
            logger.error(f"Nieoczekiwany błąd podczas ładowania promptów: {e}")
            return []

    def load_models(self) -> List[Dict[str, str]]:
        """Ładuje listę modeli z pliku CSV"""
        models = []
        try:
            with open(self.models_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    models.append(row)
            logger.info(f"Załadowano {len(models)} modeli z {self.models_file}")
        except FileNotFoundError:
            logger.error(f"Plik {self.models_file} nie został znaleziony")
        except Exception as e:
            logger.error(f"Błąd podczas ładowania modeli: {e}")

        return models

    def make_request(self, model_config: Dict[str, str], prompt: str) -> Tuple[str, float, bool]:
        """Wykonuje zapytanie do modelu LLM"""
        start_time = time.time()

        try:
            headers = {'Content-Type': 'application/json'}

            # Dodaj autoryzację jeśli jest dostępna
            if model_config.get('auth_header') and model_config.get('auth_value'):
                headers[model_config['auth_header']] = model_config['auth_value']

            # Przygotuj dane do zapytania
            data = {
                "model": model_config['model_name'],
                "messages": [{"role": "user", "content": prompt}],
                "stream": False
            }

            # Dodaj specjalne parametry jeśli są dostępne
            think = model_config.get('think')
            if isinstance(think, bool):
                data['think'] = think
            elif think in ('true', 'false'):
                data['think'] = think == 'true'
            elif think in ('low', 'medium', 'high', 'xhigh'):
                data['think'] = think

            timeout = self.config.get('timeouts', {}).get('request_timeout', 60)
            response = requests.post(
                model_config['url'],
                headers=headers,
                json=data,
                timeout=timeout
            )

            response_time = time.time() - start_time

            if response.status_code == 200:
                response_data = response.json()

                # Wyciąg odpowiedzi w zależności od formatu
                if 'message' in response_data and 'content' in response_data['message']:
                    content = response_data['message']['content']
                elif 'response' in response_data:
                    content = response_data['response']
                else:
                    content = str(response_data)

                return content, response_time, True
            else:
                logger.error(f"HTTP {response.status_code}: {response.text}")
                return f"Error: HTTP {response.status_code}", response_time, False

        except requests.exceptions.Timeout:
            response_time = time.time() - start_time
            return "Error: Request timeout", response_time, False
        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"Błąd podczas zapytania: {e}")
            return f"Error: {str(e)}", response_time, False

    def test_model(self, model_config: Dict[str, str], prompt_data: Dict[str, Any]) -> Dict[str, Any]:
        """Testuje pojedynczy model z pojedynczym promptem"""
        prompt = prompt_data['prompt']
        prompt_name = prompt_data.get('name', f"Prompt {prompt[:30]}...")
        logger.info(f"Testuję model {model_config['model_name']} z promptem: {prompt_name}")

        # Wykonaj zapytanie
        response_text, response_time, success = self.make_request(model_config, prompt)

        if not success:
            return {
                'model_name': model_config['model_name'],
                'url': model_config['url'],
                'prompt': prompt,
                'prompt_name': prompt_name,
                'success': False,
                'error': response_text,
                'response_time': response_time
            }

        # Wyciągnij kod z odpowiedzi
        code = self.evaluator.extract_python_code(response_text)

        # Oceń kod
        evaluation = self.evaluator.evaluate_code(code, prompt_data, response_time)

        return {
            'model_name': model_config['model_name'],
            'url': model_config['url'],
            'prompt': prompt,
            'prompt_name': prompt_name,
            'success': True,
            'raw_response': response_text,
            'extracted_code': code,
            'generated_code': code,  # Dodane dla kompatybilności z funkcją porównywania kodu
            'evaluation': evaluation,
            'response_time': response_time  # Dodane dla pewności, że zawsze będzie dostępne
        }

    def run_tests(self):
        """Uruchamia wszystkie testy"""
        models = self.load_models()

        if not models:
            logger.error("Brak modeli do testowania")
            return

        if not self.test_prompts:
            logger.warning("Brak promptów do testowania.")
            return

        logger.info(f"Rozpoczynam testowanie {len(models)} modeli z {len(self.test_prompts)} promptami")

        for model in models:
            for prompt_data in self.test_prompts:
                result = self.test_model(model, prompt_data)
                self.results.append(result)

                # Krótka przerwa między zapytaniami
                delay = self.config.get('timeouts', {}).get('delay_between_requests', 1)
                time.sleep(delay)

        logger.info(f"Zakończono testowanie. Zebrano {len(self.results)} wyników")

    def generate_html_report(self, output_file: str = 'allama.html', json_file: str = 'allama.json') -> str:
        """Generuje raport HTML z wynikami"""
        if not self.results:
            logger.error("Brak wyników do wygenerowania raportu")
            return ""

        # Użyj ReportGenerator do generowania raportu
        report_generator = ReportGenerator(self.config)
        report_generator.generate_html_report(
            self.results, 
            output_file=output_file,
            json_file=json_file
        )

        return output_file

    def save_results_to_json(self, output_file: str = 'allama.json'):
        """Zapisuje wyniki testów do pliku JSON"""
        if not self.results:
            logger.error("Brak wyników do zapisania do JSON")
            return
        
        # Przygotuj dane do zapisania
        export_data = {
            'timestamp': datetime.now().isoformat(),
            'models_tested': list(set(r['model_name'] for r in self.results)),
            'total_tests': len(self.results),
            'successful_tests': sum(1 for r in self.results if r['success']),
            'results': self.results
        }
        
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Wyniki zapisane do pliku JSON: {output_file}")
        except Exception as e:
            logger.error(f"Błąd podczas zapisywania wyników do JSON: {e}")


def main() -> str:
    """Główna funkcja programu"""
    parser = argparse.ArgumentParser(description="TestLLM - Testowanie modeli LLM")
    parser.add_argument(
        '--models',
        '-m',
        default='models.csv',
        help="Ścieżka do pliku CSV z modelami"
    )
    parser.add_argument(
        '--output',
        '-o',
        default='allama.html',
        help="Nazwa pliku wyjściowego raportu HTML"
    )
    parser.add_argument(
        '--json-output',
        default='allama.json',
        help="Nazwa pliku wyjściowego JSON"
    )
    parser.add_argument(
        '--config',
        '-c',
        help="Ścieżka do niestandardowego pliku konfiguracyjnego (JSON lub YAML)"
    )
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help="Nie otwieraj automatycznie raportu w przeglądarce"
    )
    parser.add_argument(
        '--publish',
        action='store_true',
        help="Publikuj wyniki na serwerze"
    )
    parser.add_argument(
        '--server-url',
        default='https://allama.sapletta.com/upload.php',
        help="URL serwera do publikowania wyników"
    )
    args = parser.parse_args()

    # Inicjalizuj i uruchom tester
    tester = LLMTester(models_file=args.models, config_path=args.config)
    tester.run_tests()
    report_path = tester.generate_html_report(output_file=args.output, json_file=args.json_output)
    
    # Automatycznie otwórz raport w przeglądarce, chyba że użytkownik wyłączył tę opcję
    if not args.no_browser:
        open_report_in_browser(report_path)
        
    # Publikuj wyniki na serwerze, jeśli opcja jest włączona
    if args.publish:
        publisher = ResultPublisher(server_url=args.server_url)
        result = publisher.publish_results(args.json_output)
        
        if result.get('success'):
            logger.info(f"Wyniki zostały pomyślnie opublikowane na serwerze")
            if 'data' in result and 'url' in result['data']:
                logger.info(f"URL wyników: {result['data']['url']}")
        else:
            logger.error(f"Błąd podczas publikowania wyników: {result.get('error', 'Nieznany błąd')}")
    
    return report_path


if __name__ == "__main__":
    main()
else:
    # Automatyczne uruchomienie benchmarku przy imporcie modułu
    # To pozwala na uruchomienie benchmarku po użyciu komendy 'allama'
    # Ale tylko jeśli moduł jest uruchamiany bezpośrednio jako skrypt
    if os.environ.get('ALLAMA_AUTO_RUN', '0') == '1':
        logger.info("Automatyczne uruchomienie benchmarku Allama")
        main()
