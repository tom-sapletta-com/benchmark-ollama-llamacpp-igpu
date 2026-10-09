"""
Moduł do publikowania wyników benchmarku na serwerze.
"""
import os
import json
import time
import hashlib
import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class ResultPublisher:
    """Klasa do publikowania wyników benchmarku na serwerze."""
    
    def __init__(self, server_url: str = "https://allama.sapletta.com/upload.php"):
        """
        Inicjalizuje obiekt ResultPublisher.
        
        Args:
            server_url: URL serwera do publikowania wyników
        """
        self.server_url = server_url
        self.last_request_time = 0
        
    def publish_results(self, json_file: str) -> Dict[str, Any]:
        """
        Publikuje wyniki benchmarku na serwerze.
        
        Args:
            json_file: Ścieżka do pliku JSON z wynikami
            
        Returns:
            Dict zawierający status publikacji i ewentualny komunikat błędu
        """
        # Sprawdź, czy plik istnieje
        if not os.path.exists(json_file):
            error_msg = f"Plik JSON nie istnieje: {json_file}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        
        # Waliduj JSON przed wysłaniem
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            error_msg = f"Nieprawidłowy format JSON: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        
        # Ogranicz częstotliwość requestów (nie częściej niż 1 na sekundę)
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < 1:
            time.sleep(1 - time_since_last_request)
        
        # Generuj timestamp i hash dla identyfikacji publikacji
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        file_hash = hashlib.md5(f"{timestamp}_{os.path.basename(json_file)}".encode()).hexdigest()
        
        # Przygotuj dane do wysłania
        files = {'file': open(json_file, 'rb')}
        data = {
            'timestamp': timestamp,
            'hash': file_hash
        }
        
        try:
            # Wyślij request
            self.last_request_time = time.time()
            response = requests.post(self.server_url, files=files, data=data, timeout=30)
            
            # Sprawdź odpowiedź
            if response.status_code == 200:
                try:
                    result = response.json()
                    if result.get('success'):
                        logger.info(f"Wyniki zostały pomyślnie opublikowane na {self.server_url}")
                        logger.info(f"URL wyników: {result.get('url', 'Brak URL')}")
                        return result
                    else:
                        error_msg = f"Błąd publikacji: {result.get('error', 'Nieznany błąd')}"
                        logger.error(error_msg)
                        return result
                except json.JSONDecodeError:
                    error_msg = "Nieprawidłowa odpowiedź serwera (nie jest to prawidłowy JSON)"
                    logger.error(error_msg)
                    return {"success": False, "error": error_msg}
            else:
                error_msg = f"Błąd HTTP: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {"success": False, "error": error_msg}
                
        except requests.RequestException as e:
            error_msg = f"Błąd podczas wysyłania danych: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
        except Exception as e:
            error_msg = f"Nieoczekiwany błąd: {str(e)}"
            logger.error(error_msg)
            return {"success": False, "error": error_msg}
