# Rubryka etapu 2 (po polsku)

Etap 1 ustalił, **co** jest nie tak z odpowiedzią. Ty ustalasz **dlaczego**, mając przed sobą pełny tekst
cytowanych dokumentów i dokumenty znalezione przez nasze własne wyszukiwanie. Ugruntowanie i wagę oceniaj według
rubryki etapu 1.

## Co jest nie tak z twierdzeniem

Najwyżej 3 problematyczne twierdzenia, najważniejsze najpierw: sprzeczne przed niepopartymi przed błędami
rozumowania, kluczowe przed pobocznymi. Gdy twierdzenie pasuje do kilku wierszy, wygrywa `CONTRADICTED_CLAIM`,
a `REASONING_ERROR` wygrywa z `UNSUPPORTED_CLAIM`.

| Kod | Kiedy |
|---|---|
| `CONTRADICTED_CLAIM` | Przeczytany dokument mówi coś konkretnego i innego w tej samej sprawie: inną liczbę, nazwę, datę, regułę lub krok. |
| `UNSUPPORTED_CLAIM` | Żaden przeczytany dokument nie podaje tego twierdzenia i żaden nie mówi czegoś innego. |
| `REASONING_ERROR` | Cytowane fragmenty zawierają właściwe fakty, ale odpowiedź źle je połączyła, wyciągnęła wniosek, którego nie wspierają, albo zastosowała regułę do niewłaściwego przypadku. |

## Sprawdzenia cytowanych dokumentów

Wykonaj je najpierw, na cytowanych dokumentach. Podaj numery dokumentów.

| Sprawdzenie | Kiedy |
|---|---|
| Nieaktualny | Cytowanemu dokumentowi w tej samej sprawie przeczy dokument z późniejszą datą albo sam dokument mówi, że został zastąpiony lub jest nieaktualny. |
| Sprzeczne | Dwa cytowane dokumenty podają różne konkretne wartości w tej samej sprawie i żaden nie jest wyraźnie nowszy. |

## Ścieżka przyczyny, pytanie po pytaniu

Dla każdego twierdzenia odpowiedz na te pytania; przyczyna wynika z twoich odpowiedzi.

| Pytanie | Reguła |
|---|---|
| 1. Czy cytowane fragmenty popierają twierdzenie? | „Popierają” znaczy: fragment to podaje albo wynika to wprost, bez dodatkowych założeń. |
| 1b. Jeśli nie: czy fragmenty zawierają właściwą treść, którą odpowiedź źle odczytała? | Wtedy przyczyną jest sama odpowiedź. |
| 2. Czy właściwa treść jest w pełnym tekście cytowanego dokumentu? | Jest w cytowanym dokumencie, ale nie we fragmencie, który dostał Bolek. |
| 3. Czy jest w innym dokumencie znalezionym przez wyszukiwanie? | Dokument, który nie był cytowany, podaje ją jasno. |

Tura bez źródeł zaczyna od pytania 3: nie ma czego sprawdzać w cytowanych.

Dla każdego dokumentu stojącego za twierdzeniem podaj jego numer i rolę: `CITED`, `HOLDS_RIGHT_ANSWER`,
`CONTRADICTS_CLAIM`, `OUTDATED` lub `CONFLICTING`.

## Potwierdzanie lub odrzucanie ustaleń etapu 1

Dla każdego kodu etapu 1: **odrzucony** tylko wtedy, gdy potrafisz wskazać fragment popierający twierdzenie
w dokumencie, który przeszedł oba sprawdzenia, albo fragment pokazujący, że sprzeczność dotyczy innego przypadku
(innego kraju, roku lub produktu). W przeciwnym razie **potwierdzony**.

## Przykłady (dokumenty i liczby są zmyślone)

| Sytuacja | Co | Dlaczego | Dokument do poprawy |
|---|---|---|---|
| Odpowiedź mówi o 6 dniach urlopu na żądanie. Cytowany fragment dotyczy zwolnienia lekarskiego; pełny tekst tego samego dokumentu mówi 4. | `CONTRADICTED_CLAIM` | `CHUNKING_ISSUE` | Cytowana polityka urlopowa |
| Ta sama odpowiedź, bez źródeł. Wyszukiwanie znajduje politykę urlopową, która mówi 4. | `CONTRADICTED_CLAIM` | `RETRIEVAL_MISS` | Polityka urlopowa |
| Odpowiedź mówi 6 dni, tak jak cytowana polityka z 2024. Polityka z 2026 znaleziona wyszukiwaniem mówi 4. | `CONTRADICTED_CLAIM` | `OUTDATED_SOURCE` | Polityka z 2024 |
| Fragment mówi, że podróże poza Europę wymagają zgody finansów; odpowiedź mówi, że wszystkie podróże. | `REASONING_ERROR` | (brak) | (brak) |
