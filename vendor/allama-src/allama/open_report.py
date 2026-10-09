"""
Moduł do automatycznego otwierania raportu HTML w przeglądarce.
"""
import os
import sys
import platform
import webbrowser
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def open_report_in_browser(report_path: str = 'allama.html') -> bool:
    """
    Otwiera raport HTML w domyślnej przeglądarce internetowej.
    
    Args:
        report_path: Ścieżka do pliku HTML z raportem
        
    Returns:
        bool: True jeśli udało się otworzyć przeglądarkę, False w przeciwnym razie
    """
    try:
        # Upewnij się, że ścieżka jest absolutna
        if not os.path.isabs(report_path):
            report_path = os.path.abspath(report_path)
            
        # Sprawdź, czy plik istnieje
        if not os.path.exists(report_path):
            logger.error(f"Nie znaleziono pliku raportu: {report_path}")
            return False
            
        # Konwertuj ścieżkę na format URL
        file_url = Path(report_path).as_uri()
        
        # Informacja o systemie
        system = platform.system().lower()
        logger.info(f"Wykryto system operacyjny: {system}")
        
        # Otwórz przeglądarkę
        logger.info(f"Otwieranie raportu w przeglądarce: {file_url}")
        
        # Próbuj otworzyć w przeglądarce
        if webbrowser.open(file_url):
            logger.info("Raport został otwarty w przeglądarce")
            return True
        else:
            logger.warning("Nie udało się otworzyć przeglądarki automatycznie")
            
            # Jeśli automatyczne otwarcie nie zadziałało, wyświetl instrukcję
            print("\n" + "="*80)
            print(f"Raport został wygenerowany: {report_path}")
            print(f"Aby wyświetlić raport, otwórz plik w przeglądarce internetowej:")
            print(f"  - Lokalizacja: {report_path}")
            if system == "windows":
                print(f"  - Komenda: start {report_path}")
            elif system == "darwin":  # macOS
                print(f"  - Komenda: open {report_path}")
            else:  # Linux i inne
                print(f"  - Komenda: xdg-open {report_path}")
            print("="*80 + "\n")
            
            return False
            
    except Exception as e:
        logger.error(f"Błąd podczas otwierania raportu: {e}")
        return False

if __name__ == "__main__":
    # Jeśli skrypt jest uruchamiany bezpośrednio, przyjmij ścieżkę jako argument
    if len(sys.argv) > 1:
        report_path = sys.argv[1]
    else:
        report_path = 'allama.html'
        
    open_report_in_browser(report_path)
