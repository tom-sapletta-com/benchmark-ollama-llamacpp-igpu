#!/usr/bin/env python3
"""
Allama - Skrypt uruchamiający benchmark modeli LLM
"""

import os
import sys

def main():
    """
    Główna funkcja uruchamiająca benchmark Allama
    """
    if len(sys.argv) > 1 and sys.argv[1] == 'benchmark':
        from allama.benchmark import main as run_profile
        return run_profile(sys.argv[2:])

    # Ustaw zmienną środowiskową, aby poinformować moduł o automatycznym uruchomieniu
    os.environ['ALLAMA_AUTO_RUN'] = '1'

    # Uruchom moduł allama.main
    try:
        from allama.main import main as run_benchmark
        
        # Uruchom benchmark i uzyskaj ścieżkę do raportu
        report_path = run_benchmark()
        print(f"Benchmark zakończony. Raport dostępny w: {report_path}")
        return report_path
        
    except ImportError:
        print("Nie można zaimportować modułu allama.main. Upewnij się, że pakiet jest zainstalowany.")
        sys.exit(1)
    except Exception as e:
        print(f"Wystąpił błąd podczas uruchamiania benchmarku: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
