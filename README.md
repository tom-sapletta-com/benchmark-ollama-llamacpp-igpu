# Benchmark Ollama / llama.cpp na iGPU

Pełne wyniki benchmarków wykonanych na **minis** 8–9 października 2026 r., z odpowiedziami modeli, testami kodu, promptami, pomiarami i pochodzeniem modeli.

Sprzęt: **AMD Ryzen 9 7940HS, Radeon 780M, 64 GB DDR5, 16 GiB pamięci zarezerwowanej dla iGPU**. Ubuntu 24.04.5, Mesa 25.2.8, Vulkan 1.4.318. Pamięć UMA jest współdzielona; rezerwacja 16 GiB nie oznacza odrębnych 16 GiB VRAM.

## Jakość kodu: generowanie i dwie naprawy

Wcześniejsze raporty badały szybkość i testy funkcjonalne sześciu małych funkcji. Nie obejmowały zmian w istniejącym kodzie ani osobnego raportu regresji i czytelności. Dodano [raport jakości trzech use case](results/coding-quality-20261009/index.html), [pełne odpowiedzi](results/coding-quality-20261009/results.json) i [fixtures z testami i referencjami](results/coding-quality-20261009/cases.json).

| Use case | Zakres | Sprawdzane zachowanie |
| --- | --- | --- |
| Generowanie agregatora faktur NDJSON | `invoice_summary.py` | Decimal, sumowanie przed zaokrągleniem, walidacja, numery błędnych linii, sortowanie wyników |
| Naprawa cache TTL + LRU | `ttl_cache.py` | Granica wygaśnięcia, odczyt bez przedłużania TTL, LRU, nadpisanie, usuwanie wygasłych wpisów, parametry |
| Naprawa rozliczenia faktury | `money.py`, `cart.py`, `invoice.py` | Dokładne grosze, mnożenie przed zaokrągleniem, rabat całej faktury, walidacja i zachowanie wejścia |

**Zmierzony wynik GPT-OSS 20B Q8: 2/9 w pełni poprawnych odpowiedzi.**

| Use case | Pełne zaliczenia | Testy poprawności | Testy kompatybilności/regresji | Wykryty problem |
| --- | ---: | ---: | ---: | --- |
| Generowanie | 2/3 | 16/24 | 8/12 | Jedna odpowiedź zawierała błąd składni w przykładzie z zagnieżdżonymi potrójnymi cudzysłowami; testów tej odpowiedzi nie uruchomiono |
| Naprawa jednego pliku | 0/3 | 21/24 | 12/12 | Nadpisanie klucza w pełnym cache usuwało inny, nadal ważny wpis |
| Naprawa trzech plików | 0/3 | 21/24 | 12/12 | Cena jednostkowa była zaokrąglana przed mnożeniem: `0.005 × 2` dawało 2 grosze zamiast 1 |

Wykonano 96 metod testowych: 90 zaliczeń i 6 niezaliczeń. Pozostałych 12 metod nie uruchomiono z powodu błędu składni. „0 zaliczeń” przy takiej odpowiedzi oznacza brak działającego rozwiązania, nie wykonanie tych testów. Wszystkie poprawnie sparsowane odpowiedzi zmieniły wyłącznie wymagane pliki. Wynik pokazuje ograniczenia badanego modelu i promptu; nie jest porównaniem innych modeli ani trybów rozumowania.

Każda próba ma **8 testów poprawności + 4 testy kompatybilności/regresji**. Metoda z podprzypadkami zalicza się dopiero po zaliczeniu ich wszystkich. Dla generowania „regresja” oznacza zgodność podstawowego kontraktu, ponieważ wejście zawiera tylko stub. Model widzi specyfikację i pliki wejściowe; nie widzi kodu testów ani referencji. Zwraca pełne pliki w JSON. Nie dostaje informacji o błędach ani kolejnej szansy naprawy w ramach próby. Zapisujemy też nieudane i niekompletne odpowiedzi.

Prawidłowy zakres oznacza zmianę dokładnie żądanych plików, bez modyfikacji testów i dodatkowych ścieżek. Statyczny przegląd AST podaje długość funkcji, liczbę rozgałęzień, dokumentację, adnotacje i ostrzeżenia. To wskaźniki do przeglądu; nie zastępują oceny architektury, czytelności i bezpieczeństwa. Nie wyliczamy arbitralnej zbiorczej oceny jakości.

Kontrole: każda referencja musi zaliczyć 12/12, każda wersja wejściowa musi zawieść. Dla naprawy trzech plików przywrócenie osobno każdego wadliwego pliku również musi spowodować błąd. Kod modelu jest uruchamiany jako użytkownik bez uprawnień w przypiętym obrazie Python 3.12, bez sieci i zapisu do repozytorium, z limitami CPU/RAM/procesów oraz zapisem wyłącznie do tymczasowego `/work`.

Podczas pomiaru poprawiono też benchmark: pierwszy ewaluator odrzucał legalny import `__future__`, a test numeru linii rozróżniał wielkość liter w słowie „line”. [Pierwszy przebieg](results/coding-quality-initial-20261009/results.json) i jego testy oraz dokładny początkowy skrypt zachowano. Po korekcie oceniono ponownie **te same bajty odpowiedzi**, bez ponownego generowania i bez ręcznych napraw kodu. [tools/recheck_quality.py](tools/recheck_quality.py) pozwala odtworzyć tę korektę; weryfikator sprawdza identyczność odpowiedzi, promptów i czasów z pierwszym przebiegiem.

Pomiar dotyczy **jednego wdrożonego GPT-OSS 20B w Ollama Q8/MXFP4**, z natywnym szablonem rozmowy, `think=low`, temperaturą 0, seed 42, kontekstem 16384 i limitem 8192 tokenów, z formatem odpowiedzi JSON. Trzy powtórzenia tego samego promptu mierzą powtarzalność; nie tworzą dziewięciu niezależnych zadań. Wyników nie łączymy z historycznymi medianami silników ani z rankingiem modeli. Nie przeprowadzono niezależnej oceny przez ludzi.

Odtworzenie trzech use case na już działającym Ollama:

```bash
DOCKER_HOST=ssh://tom@minis .venv/bin/python tools/quality_benchmark.py \
  --url http://minis:11434 --model gpt-oss-minis-code:20b \
  --output replays/coding-quality --repeats 3
```

Spójność zapisanego raportu: `python3 tools/verify_quality.py`. Skrypt sprawdza również nieudane próby; FAIL modelu jest wynikiem benchmarku, a nie powodem usunięcia danych.

## OpenCode: Gemma 12B vs GPT-OSS 20B na zadaniu Koru

| Model | Wykonane zadanie | Testy | CC≤15 | Czas | VRAM, szczyt |
|---|---|---|---|---|---|
| `gemma4:12b` | FAIL | 24/24 | FAIL | 396.3 s | 9.09 GiB |
| `gpt-oss:20b` | FAIL | 18/24 | PASS | 150.2 s | 12.53 GiB |

[Raport OpenCode](results/opencode-koru-20261009/index.html) porównuje dokładne lokalne tagi `gemma4:12b` i `gpt-oss:20b` podczas wykonywania **STARTER-614 z historii Planfile Koru**: refaktoryzacji `sse_log_stream` w `src/koruapi/dashboard_logs.py`. Bieżąca kolejka zawiera analizę projektu i instalację; kod w aktualnym `main` już ma wcześniejszą refaktoryzację. Dlatego odtwarzamy rzeczywiste zadanie na przypiętym kodzie sprzed tej zmiany, bez zamykania zadania Planfile i bez zmiany bieżącego repozytorium Koru.

- Źródło: `semcod/koru`, baza `f248f4e5331e75c242ef33f170447acf2a7f550d`; istniejąca refaktoryzacja referencyjna: `01c2810445da0b139696ec637093f7f858d72be1`. Apache-2.0, źródło/testy/licencja i SHA256 w [fixture](results/opencode-koru-20261009/fixture) oraz [provenance.json](results/opencode-koru-20261009/provenance.json).
- Historyczny ticket podawał code2llm CC=25. Przypięty Ruff mierzy CC=19. Próg akceptacji: wszystkie funkcje w module ≤15, działający kod, poprawny lint i zmiana dokładnie wymaganego pliku.
- **16 oryginalnych testów modułu + 8 dodatkowych testów zachowania**, których agent nie widzi. Badamy poziomy logów, historię, zatrzymanie strumienia, oba źródła logów, Unicode, rotację i brak dostępu. Testy zachowują istniejącą semantykę, również kolejność sprawdzania limitu zdarzeń. Nie testujemy naprawy tego limitu.
- OpenCode 1.17.8, nowa sesja/kontener dla każdej próby. Jedna świeża próba na model, kolejność AB: Gemma → GPT-OSS. Budżet: 8 kroków, 480 sekund, 16K kontekstu, 4096 tokenów na odpowiedź, temperatura 0, seed 42 w efektywnych żądaniach. GPT-OSS ma `reasoning_effort=low`; Gemma domyślne zachowanie serwera. Te tryby nie są identyczne.
- Agent ma narzędzia do odczytu, edycji i uruchamiania widocznych testów; wykonane działania zachowano w przebiegu. Kontroler ocenia końcowy kod w osobnym kontenerze bez sieci i z plikami tylko do odczytu. Kontrola bazowa: 24/24 testów i FAIL CC; referencja: 24/24 i PASS CC.
- `gemma4:12b`: lokalny Q4_K_M, metadane i digest odczytane z minis. **`gpt-oss:20b` jest oryginalnym MXFP4 + BF16**, odrębnym od produkcyjnego Q8. Po pomiarach przywracamy załadowany `gpt-oss-minis-code:20b` Q8. To porównanie modeli i ustawień, nie izolowana próba formatu wag.
- Czas obejmuje cały przebieg OpenCode i narzędzi, poza wstępnym załadowaniem/rozgrzewką modelu. Sysfs próbkujemy co 0,5 s. Licznik API size_vram Gemmy jest niższy niż zajętość widoczna w sterowniku; zachowujemy oba odczyty i prezentujemy pomiar sterownika. VRAM i GTT są **wartościami bezwzględnymi**, bez odejmowania wcześniejszego modelu. Tokeny pochodzą z liczników strumienia API; pełne żądania, odpowiedzi, zdarzenia narzędzi, diffy i próbki zasobów są w danych.

Poprawiono zależności pomiaru: pierwszy zestaw obejmował niezwiązane testy innych części dashboardu; zawężono selektory do modułu SSE. Pierwsza sesja OpenCode napotkała błąd wykonania pobranego ripgrep na Dockerowym `/tmp` z `noexec`; jawne `exec` umożliwiło narzędziom działanie w izolowanym kontenerze. OpenCode odrzucał także edycję w katalogu bez Git mimo wzorców uprawnień; poprawiono konfigurację, a zakres zapisu wymusza teraz system plików: tylko docelowy plik jest zapisywalny dla UID 65534, pozostałe pliki i katalogi są tylko do odczytu. Każda próba sprawdza to przed uruchomieniem agenta. Pierwszą kontrolę i zdarzenia awarii zachowano w `evidence/validation/opencode-*`; wykluczono je z wyników modeli.

Dodatkowe testy poprawiono, aby podmieniały standardowe `time.sleep`, bez wymagania prywatnego importu w module. Ponownie oceniono niezmienione odpowiedzi i obie kontrole; wyniki zaliczeń pozostały takie same. Początkowe testy oraz `controller-results.json` zachowano.

**Oba modele nie wykonały całego zadania.** Gemma nie zmieniła kodu i zakończyła ostatnią odpowiedź na limicie tokenów. GPT-OSS zmienił plik i przeszedł oryginalne 16 testów oraz CC, lecz oblał 6 z 8 dodatkowych testów: użył generatora jak zwykłej pary wartości i usunął import `time`, pozostawiając `time.sleep` (F821). Szybsze wykonanie nie oznacza poprawnego rozwiązania.

To **jeden historyczny problem, jedna próba na model i testy wybranego modułu**, bez pełnej kwalifikacji Koru, publikacji kodu modelu, pomiaru energii i ogólnego rankingu modeli. Konfiguracja agenta i uprawnień korzysta z [dokumentacji OpenCode Agents](https://opencode.ai/docs/agents/) oraz [Permissions](https://opencode.ai/docs/permissions/). Skrypty przygotowania/kontroli: `tools/opencode_compare_remote.py`, `tools/opencode_verify.py`, `tools/opencode_sandbox.Dockerfile`; offline: `python3 tools/verify_opencode.py`.

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
| [results/opencode-koru-20261009](results/opencode-koru-20261009) | OpenCode + Gemma/GPT-OSS na historycznym zadaniu Koru Planfile: testy, zmiany, API i GPU/RAM |
| [results/coding-quality-20261009](results/coding-quality-20261009) | Trzy use case: generowanie, naprawa jednego pliku, naprawa trzech plików; testy, regresje, diff i wskaźniki AST |
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
