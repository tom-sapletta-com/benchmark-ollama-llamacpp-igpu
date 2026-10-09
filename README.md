# Benchmark Ollama / llama.cpp na iGPU

Pełne wyniki benchmarków wykonanych na **minis** 8–9 października 2026 r., z odpowiedziami modeli, testami kodu, promptami, pomiarami i pochodzeniem modeli.

Sprzęt: **AMD Ryzen 9 7940HS, Radeon 780M, 64 GB DDR5, 16 GiB pamięci zarezerwowanej dla iGPU**. Ubuntu 24.04.5, Mesa 25.2.8, Vulkan 1.4.318. Pamięć UMA jest współdzielona; rezerwacja 16 GiB nie oznacza odrębnych 16 GiB VRAM.

## Wyniki GPT-OSS 20B — 9 października

Wszystkie profile mają 72 tensory ekspertów **MXFP4**. Oznaczenie **Q8** dotyczy 98 macierzy attention/output/embedding, a nie całego modelu. Warianty Q8/Q8 i BF16/BF16 mają odpowiednio identyczne wszystkie 459 tensorów.

| Silnik / pozostałe macierze | Testy kodu | Tokeny/s, mediana API | Pełna odpowiedź, mediana | Przyrost VRAM | Przyrost GTT |
| --- | ---: | ---: | ---: | ---: | ---: |
| llama.cpp / Q8_0 | 18/18 | 28,85 | 11,19 s | 11,10 GiB | 0,61 GiB |
| Ollama / Q8_0 | 18/18 | 29,10 | 11,01 s | 11,19 GiB | 0,63 GiB |
| llama.cpp / BF16 | 18/18 | 20,53 | 15,38 s | 12,16 GiB | 1,11 GiB |
| Ollama / BF16 | 18/18 | 20,67 | 14,47 s | 12,25 GiB | 1,13 GiB |

**72/72 rozwiązań przeszło testy kodu:** 6 różnych zadań × 3 powtórzenia × 4 profile. To wynik małego zestawu, nie dowód poprawności dowolnych zadań programistycznych.

**Q8 przyspieszył generowanie o około 40% względem BF16.** Przy identycznych wagach oba silniki generują z podobną szybkością. Definicje szybkości API różnią się sposobem liczenia pierwszego tokenu. Porównywalna mediana ze strumienia, `(liczba tokenów − 1)/(czas całkowity − czas pierwszego tokenu)`, wynosi **28,82 vs 29,00 tokenów/s** dla Q8; różnica poniżej 1% nie uzasadnia ogólnego wyboru zwycięzcy.

### Dłuższe wejście: 4957 tokenów

| Profil | Pierwszy token, mediana | Pełna odpowiedź, mediana | Poprawność |
| --- | ---: | ---: | ---: |
| llama.cpp / Q8 | 13,74 s | 14,53 s | 3/3 |
| Ollama / Q8 | 9,43 s | 10,13 s | 3/3 |
| llama.cpp / BF16 | 16,96 s | 18,00 s | 3/3 |
| Ollama / BF16 | 12,20 s | 13,15 s | 3/3 |

Ollama szybciej przetwarzała dłuższe wejście przy zmierzonych ustawieniach. llama.cpp miał microbatch 128; Ollama może inaczej organizować wewnętrzne batchowanie. Pierwszy token może należeć do rozumowania. Test ten nie jest wliczony do median zadań programistycznych.

## Wcześniejszy benchmark — 8 października

Zachowano cały raport, odpowiedzi, odrzucone próby po zakłóceniach, wznowienia i pomiary sterownika. Każdy model miał 6 zadań × 2 powtórzenia. Parametry, tokenizer, tryb rozumowania i użycie MTP różniły się między modelami; tego zestawu nie należy łączyć ze sparowanym porównaniem silników.

| Lokalna nazwa modelu w Ollama | Testy kodu | Tokeny/s, mediana |
| --- | ---: | ---: |
| `gpt-oss:20b` | 12/12 | 20,65 |
| `gemma4:12b` | 12/12 | 25,87 |
| `qwen3.8:27b` | 12/12 | 11,98 |
| `qwen3.5:9b` | 8/12 | 14,36 |
| `devstral-small-2:24b` | 9/12 | 5,74 |

Nazwy pochodzą z lokalnych tagów i zapisanych metadanych. Wartości pamięci z API starego raportu nie są równoważne pomiarowi sterownika w nowym porównaniu; szczególnie MTP może powodować zaniżanie raportowanego przydziału.

## Stan wdrożenia na minis

Po benchmarku początkowo przywrócono llama.cpp. **Na kolejne polecenie właściciela 9 października wdrożono Ollama Q8**:

- `ollama.service`: aktywna i włączona w autostarcie; `llamacpp-gpt-oss.service`: zatrzymana i wyłączona z autostartu.
- Stabilna nazwa `gpt-oss-minis-code:20b` wskazuje teraz model Q8, ze szablonem rozmowy, obsługą narzędzi i licencją odziedziczonymi z wcześniejszego modelu.
- Kontekst 16384, jeden równoległy slot i jeden załadowany model, Vulkan, Flash Attention, KV f16, 8 wątków, logiczny batch 512.
- `/api/ps` potwierdziło pełne umieszczenie modelu w GPU. Pola `quantization_level: unknown` dotyczą mieszanego formatu; pochodzenie Q8 potwierdza SHA256 i zestawienie tensorów.
- Poprzedni alias BF16 zachowano jako `gpt-oss-minis-bf16-backup-20261009:20b`. Alias użyty w benchmarku Q8 pozostał bez zmian.
- OpenWebUI używa natywnego lokalnego Ollama; zachowano użytkowników i historię. Lokalny endpoint zgodny z API OpenAI nadal obsługuje istniejące konfiguracje klientów kodowania.

Potwierdzenia znajdują się w [evidence/deployment](evidence/deployment). Przenośny skrypt odtwarzania uruchomiono dodatkowo na wdrożonym Ollama Q8: 6/6 zadań i 1/1 próbę dłuższego wejścia zaliczono; zapisano je osobno w `results/production-replay-20261009`. Powtórnie sprawdzono też wszystkie 72 historyczne odpowiedzi w izolowanym Dockerze: 72/72 zaliczeń. Historyczny zapis przywrócenia llama.cpp pozostaje w danych pomiarowych; nie jest opisem późniejszego wdrożenia.

## Zawartość archiwum

| Ścieżka | Zawartość |
| --- | --- |
| [results/minis-20261009](results/minis-20261009) | Końcowe 72 próby kodowania i 12 prób długiego wejścia; dokładne prompty, początkowy zestaw 54 prób, przerwana próba i logi |
| [results/minis-20261008](results/minis-20261008) | Wcześniejsze 60 prób pięciu modeli; odpowiedzi, testy, zakłócenia i metryki |
| [evidence/model-parity](evidence/model-parity) | SHA256 modeli, przypięte rewizje, typy/wymiary/hashes wszystkich tensorów, sparsowane nagłówki GGUF |
| [evidence/validation](evidence/validation) | Sprawdzenia danych, referencyjnych rozwiązań, sandboxa, ekstrakcji odpowiedzi, odtworzenia usług i przeglądarki |
| [evidence/scripts-as-run](evidence/scripts-as-run) | Dokładne skrypty użyte podczas pomiarów i wdrożenia; zachowane historyczne ścieżki i polecenia usług |
| [vendor/allama-src](vendor/allama-src) | Kod biblioteki Allama i kontrakty sześciu zadań z lokalnego snapshotu `4e3578ae9e4b616cc1900c5ffd872954c12dcb77` |
| [tools](tools) | Przenośna weryfikacja archiwum, ponowne wykonanie promptów i testów kodu, odtworzenie modelu Q8 |
| [manifest.json](manifest.json), [SHA256SUMS](SHA256SUMS) | Inwentarz i kontrola integralności |

Wagi modeli, prywatna baza OpenWebUI, hasła, tokeny i profile przeglądarki nie należą do archiwum wyników.

## Otwieranie raportów

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

Otwórz `http://127.0.0.1:8000/` i wybierz raport. Strony są statyczne i zawierają odpowiedzi oraz testy. Pełne dane są w `results.json` przy każdym raporcie. Lokalny raport na minis jest dostępny pod `http://minis:3001/llamacpp-vs-ollama-20261009/`.

## Weryfikacja zapisanych wyników

Kontrola integralności i spójności danych nie wymaga GPU ani dodatkowych pakietów:

```bash
python3 tools/verify_results.py
```

Instalacja zależności oraz sprawdzenie kontraktów zadań i adaptera:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest -q tests vendor/allama-src/tests/test_benchmark_contracts.py
```

Ponowne sprawdzenie wszystkich 72 zapisanych odpowiedzi w tym samym izolowanym Dockerze:

```bash
mkdir -p replays
.venv/bin/python tools/recheck_saved_code.py --output replays/rechecked.json
```

Można wskazać zdalny Docker standardową zmienną `DOCKER_HOST=ssh://uzytkownik@host`. Ewaluator używa przypiętego obrazu Python 3.12, bez sieci, z ograniczeniami CPU/RAM, wyłączonymi capabilities i systemem plików tylko do odczytu.

## Powtórzenie promptów na własnym silniku

Przygotuj ręcznie wybrany model i silnik z kontekstem 16384 oraz pełnym offloadem GPU. Porównuj silniki kolejno, bez innych zapytań do GPU. Skrypt nie pobiera modeli, nie zmienia usług i nie weryfikuje samodzielnie wag ani braku innych obciążeń. Wariant w nowym raporcie jest deklaracją wywołującego.

```bash
.venv/bin/python tools/replay.py \
  --runtime ollama --variant q8 \
  --url http://localhost:11434 --model gpt-oss-minis-code:20b \
  --output replays/ollama-q8 --repeats 3

.venv/bin/python tools/replay.py \
  --runtime llama --variant q8 \
  --url http://localhost:8080 --model gpt-oss-minis-code:20b \
  --output replays/llama-q8 --repeats 3
```

Do powtórzenia pełnej kontrolowanej kolejności i pomiarów sterownika służy opis metody w zapisanym raporcie oraz historyczne skrypty w `evidence/scripts-as-run`. Te skrypty są dokumentacją pomiaru na minis i zawierają przełączanie usług; przenośnym punktem wejścia jest `tools/replay.py`.

## Odtworzenie dokładnego modelu Ollama Q8

Źródła są przypięte w [evidence/model-parity](evidence/model-parity). Model upstream znajduje się w `ggml-org/gpt-oss-20b-GGUF` w rewizji `ef9b12f2ff56c69cf32153a02784e7a3c88bf524`; oryginalny blob Ollama BF16 jest zidentyfikowany pełnym SHA256.

```bash
python3 tools/repack_q8.py \
  --ollama-bf16 /path/to/original-ollama-bf16.gguf \
  --upstream-q8 /path/to/gpt-oss-20b-MXFP4.gguf \
  --output /path/to/gpt-oss-ollama-q8.gguf
```

Skrypt weryfikuje oba wejścia, kopiuje niezmienione bajty 459 tensorów Q8/MXFP4/F32 i dostosowuje oryginalny nagłówek Ollama. Oczekiwany SHA256 wyjścia:

```text
214b01ff392ec0d991c766ceccba11948c1208c3aa8272b63a5170d802c1866e
```

Do zwykłych rozmów i narzędzi należy również dołączyć szablon GPT-OSS. Pełny przebieg tego kroku zapisano w `evidence/scripts-as-run/deploy-ollama-q8.py`.

## Metoda i ograniczenia

- Dokładnie te same bajty promptów Harmony dla sparowanych prób; temperatura 0, seed 42, tryb low, limit 1024 tokenów odpowiedzi.
- Sześć zadań: deduplikacja list, łączenie przedziałów, agregacja CSV z Decimal, sortowanie topologiczne, głębokie łączenie słowników, LRU O(1).
- Pierwsze trzy profile zmierzono w trzech zmiennych kolejnościach. Dodatkowy profil Ollama Q8 wykonano później, po trzech oddzielnych załadowaniach. Nie był częścią zrównoważonego porządku czterech profili.
- Zapisano rozgrzewki, rzeczywiste liczniki tokenów, temperatury CPU, przyrost VRAM i osobno GTT. Czasy testów kodu nie wchodzą do czasu odpowiedzi modelu.
- Nie mierzono energii. Powtórzenia nie są niezależnymi zadaniami. Inny kontekst, batch, prompt, wersja sterownika lub długie zadanie może zmienić rezultat.

## Pochodzenie i licencja

Benchmark korzysta z [wronai/allama](https://github.com/wronai/allama), Apache-2.0. Lokalny snapshot rozszerzenia benchmarku został zachowany w `vendor/allama-src`; jego lokalny commit nie jest deklaracją opublikowanej wersji upstream. Kod tego repozytorium jest objęty Apache-2.0; [LICENSE](LICENSE).

Dokumentacja silników: [Ollama generate](https://docs.ollama.com/api/generate), [Ollama create](https://docs.ollama.com/api/create), [llama.cpp — przypięta dokumentacja serwera](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/tools/server/README.md).
