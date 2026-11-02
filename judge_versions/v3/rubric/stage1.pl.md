# Rubryka etapu 1 (po polsku)

Oceniasz jedną turę Bolka, firmowego asystenta: pytanie użytkownika i odpowiedź Bolka. Wypełniasz stały formularz.
Każde pole ma zamkniętą listę wartości; nie ma w nim wolnego tekstu.

## Zasady ogólne

1. Oceniaj tylko na podstawie tego, co dostajesz: pytania, odpowiedzi, wcześniejszych tur i dowodów. Nie wiesz, co
   jest prawdą w firmie.
2. Twierdzenie jest błędne tylko wtedy, gdy dowody mówią coś innego. Jeśli dowody nic o nim nie mówią, twierdzenie
   jest niepoparte, a nie błędne.
3. Między dwoma poziomami wybierz niższy tylko wtedy, gdy potrafisz wskazać konkretną wadę, która wyklucza wyższy.
   W przeciwnym razie wybierz wyższy.
4. Oceniaj każde pole osobno. Jasna odpowiedź może być błędna, a poprawna może być trudna w odbiorze.
5. Pomijaj (null) pola, które nie dotyczą danej intencji. Nie zgaduj ich.
6. Oceniaj treść, nie język, chyba że język odpowiedzi różni się od języka pytania.

**Kluczowe twierdzenie** to takie, na podstawie którego użytkownik coś zrobi: liczba, nazwa, data, reguła, krok,
miejsce lub link.

Dane osobowe w rozmowie są zastąpione znacznikami, np. `<PERSON_1>`. Ten sam znacznik oznacza tę samą wartość
wszędzie, także w dokumentach.

## Intencja

| Wartość | Pytanie |
|---|---|
| `FACT_LOOKUP` | Prosi o fakt dotyczący firmy: liczbę, regułę, datę, właściciela procesu, politykę. |
| `HOW_TO` | Pyta, jak coś zrobić: kroki, procedura. |
| `TROUBLESHOOTING` | Opisuje problem lub błąd i pyta, jak go naprawić. |
| `PEOPLE_LOOKUP` | Pyta o ludzi: kim ktoś jest, kto jest właścicielem czegoś, w jakim zespole ktoś pracuje. |
| `DATA_QUESTION` | Pyta o dane: tabele, pola, metryki, jak je odpytać. |
| `GENERAL_TASK` | Prosi o ogólną pracę bez wiedzy firmowej: napisz, przetłumacz, streść, zaprogramuj. |
| `CHITCHAT` | Powitanie, podziękowanie, rozmowa towarzyska. |
| `OTHER` | Wszystko inne, także pytania zbyt ogólne, by je zaklasyfikować. |

`FACT_LOOKUP`, `HOW_TO`, `TROUBLESHOOTING` i `DATA_QUESTION` to **intencje wiedzy**.

## Które pola dotyczą której intencji

| Intencja | Oceny | Ugruntowanie | Typy błędów |
|---|---|---|---|
| Intencje wiedzy | Trafność, kompletność, jasność | Tylko gdy tura ma dowody (własne źródła lub źródła wcześniejszych tur) | Wszystkie kody etapu 1 |
| `PEOPLE_LOOKUP` | Tylko trafność | Nie | Żaden z ocenianych kodów |
| `GENERAL_TASK`, `CHITCHAT` | Trafność, kompletność, jasność | Nie | `INCOMPLETE_ANSWER`, `MISUNDERSTOOD_QUERY`, `PRESENTATION_ISSUE`, `AMBIGUOUS_QUESTION`, `OUT_OF_SCOPE` |
| `OTHER` | Trafność, kompletność, jasność | Nie | `AMBIGUOUS_QUESTION`, `OUT_OF_SCOPE` |

„Wymaga wiedzy wewnętrznej” określasz tylko dla intencji wiedzy. Liczby fragmentów odpowiedzi podajesz tylko dla
tur wiedzy z dowodami, których odpowiedź log dzieli na fragmenty.

## Temat

Temat to obszar wiedzy tury. Gdy tura ma źródła, tematem jest magazyn danych tych źródeł; gdy pochodzą z kilku
magazynów, wybierz jeden z nich. Wybieraj dowolnie tylko wtedy, gdy źródeł nie ma; gdy nic nie pasuje, użyj `OTHER`.

## Poziomy ocen

Dwie granice zamieniają trafność i ugruntowanie w decyzje: 2 lub mniej oznacza turę do dalszej analizy, a 4 lub
więcej jest potrzebne do dobrej odpowiedzi. Dlatego poziomy są najostrzejsze przy 2 i 4, a 3 znaczy „ani to, ani to”.

| Poziom | Trafność: czy odpowiada na to pytanie? | Kompletność: czy obejmuje każdą część? | Jasność: czy łatwo ją czytać i użyć? | Ugruntowanie: czy dowody ją popierają? |
|---|---|---|---|---|
| 5 | Odpowiada dokładnie na zadane pytanie, wprost, na początku. | Obejmuje każdą część, z tym, czego użytkownik potrzebuje do działania: kroki, warunki, wyjątki. | Od razu łatwa do przeczytania i użycia. Odpowiedź jest na początku; struktura i formatowanie pasują do treści. | Każde twierdzenie jest poparte. |
| 4 | Odpowiada na pytanie, z dygresją lub materiałem, którego użytkownik nie potrzebował. Także: uzasadniona odmowa pytania spoza zakresu albo dopytanie, gdy pytanie naprawdę jest niejednoznaczne. | Obejmuje każdą część. Brakuje drobnego szczegółu, bez którego użytkownik się obejdzie. | Jasna, ale dłuższa lub mniej uporządkowana niż trzeba. | Każde kluczowe twierdzenie jest poparte. Tylko uwagi poboczne lub wiedza ogólna nie mają poparcia. |
| 3 | Częściowo trafna: odpowiada na szersze lub pokrewne pytanie i użytkownik musi szukać odpowiedzi. | Brakuje jednej części pytania wieloczęściowego albo głównej części brakuje warunku lub kroku, którego użytkownik potrzebuje. | Używalna z wysiłkiem: rozwlekła, źle uporządkowana albo z niewyjaśnionym żargonem. | Większość kluczowych twierdzeń jest poparta, co najmniej jedno nie. Nic nie jest sprzeczne. |
| 2 | W większości nietrafna: o temacie, nie o pytaniu. | Odpowiada tylko na małą część pytania. | Trudna do zrozumienia: chaotyczna, miesza języki albo formatowanie ukrywa treść. | Większość kluczowych twierdzeń nie jest poparta albo jedno kluczowe twierdzenie jest sprzeczne z dowodami. |
| 1 | Nie odpowiada: odpowiada na inne pytanie, odmawia bez powodu albo jest pusta. | Nie odpowiada na nic istotnego. | Bezużyteczna: nieczytelna, w całości w złym języku albo uszkodzona. | Jako całość nie ma oparcia w dowodach albo jej główna myśl jest z nimi sprzeczna. |

- Kompletność dotyczy pytania, nie dokumentów. Pominięcie treści dokumentu, o którą użytkownik nie pytał, nie jest
  wadą.
- Przy ugruntowaniu liczby fragmentów odpowiedzi są wskazówką, ale nie ma wzoru: jedno niepoparte kluczowe
  twierdzenie waży więcej niż kilka niepopartych uwag pobocznych. Sprawdź każdy fragment odpowiedzi ze źródłami,
  na które wskazuje.
- Sprzeczne kluczowe twierdzenie zawsze oznacza ugruntowanie 2 lub niższe, `CONTRADICTED_CLAIM` i `HIGH`.
- Kluczowe twierdzenie jest sprzeczne, gdy jakikolwiek fragment dowodów mówi coś konkretnego i innego w tej samej
  sprawie, nawet jeśli inny przypis je popiera. Dwa przypisy, które się różnią, nie znoszą się nawzajem.

## Relacja do poprzedniej tury

Poprzednia tura to tura przed nią w tej samej sesji, także gdy przerwa rozpoczęła nowy segment. Jeśli pasują dwie
wartości, wygrywa pierwsza w tej kolejności: `CORRECTION`, `FRUSTRATION`, `REPHRASE`, `FOLLOW_UP`, `NEW_TOPIC`.

| Wartość | Tura użytkownika |
|---|---|
| `FIRST` | Nie ma poprzedniej tury albo tekst poprzedniej tury jest już usunięty. |
| `CORRECTION` | Mówi lub pokazuje, że poprzednia odpowiedź była błędna: „to nieprawda”, „to 4 dni, nie 6”. |
| `FRUSTRATION` | Okazuje irytację lub rezygnuje: „bezużyteczne”, „nieważne”. |
| `REPHRASE` | Pyta o to samo innymi słowami, nie mówiąc, że odpowiedź była błędna. |
| `FOLLOW_UP` | Buduje na poprzedniej odpowiedzi: następny krok, szczegół, pokrewne pytanie. |
| `NEW_TOPIC` | Nie ma nic wspólnego z poprzednią turą. |

## Sprawdzenia tak / nie

| Sprawdzenie | Prawda, gdy |
|---|---|
| Wymaga wiedzy wewnętrznej | Poprawna odpowiedź zależy od czegoś specyficznego dla naszej firmy: reguły, procesu, systemu, liczby, nazwy lub dokumentu. „Jak zarezerwować podróż służbową?” – prawda; „Jak napisać JOIN w SQL?” – fałsz; „Jak odpytać naszą tabelę kampanii?” – prawda. |
| Język odpowiedzi się zgadza | Odpowiedź jest głównie w języku pytania. Kod, nazwy i cytowany tekst dokumentów się nie liczą. |
| Odmowa lub pusta odpowiedź | Odpowiedź odmawia albo nie ma istotnej treści. |
| Sprzeczna z wcześniejszą odpowiedzią | Kluczowe twierdzenie różni się od kluczowego twierdzenia wcześniejszej odpowiedzi w tej samej sesji. |

## Typy błędów, które możesz zapisać

Zapisz kod tylko wtedy, gdy potrafisz wskazać konkretną rzecz z tabeli. Jeśli nie potrafisz, nie zapisuj go. Gdy nie
zapiszesz żadnego kodu, tura nie ma zidentyfikowanego problemu.

| Kod | Znaczenie | Musisz umieć wskazać |
|---|---|---|
| `CONTRADICTED_CLAIM` | Kluczowe twierdzenie jest sprzeczne z dowodami: inna liczba, nazwa, data, reguła lub krok. | Kluczowe twierdzenie i fragment dowodów, który mówi coś konkretnego i innego w tej samej sprawie |
| `UNSUPPORTED_CLAIM` | Kluczowe twierdzenie nie jest poparte dowodami i żaden dowód mu nie przeczy. | Kluczowe twierdzenie, którego nie popiera żaden dowód |
| `INCOMPLETE_ANSWER` | Część pytania pozostała bez odpowiedzi. | Część pytania, której odpowiedź nie dotyczy |
| `MISUNDERSTOOD_QUERY` | Odpowiedziano na inne pytanie. | Inne pytanie, na które odpowiedziano zamiast tego |
| `PRESENTATION_ISSUE` | Zły język lub zepsute formatowanie. | Zły język albo formatowanie, które ukrywa treść |
| `AMBIGUOUS_QUESTION` | Zbyt ogólne, by dobrze odpowiedzieć; Bolek powinien był dopytać. | Dwa znaczenia pytania wymagające różnych odpowiedzi, z których Bolek wybrał jedno bez pytania |
| `OUT_OF_SCOPE` | Nie jest czymś, na co Bolek powinien lub może odpowiedzieć. Kod dotyczy pytania: zapisz go także wtedy, gdy Bolek słusznie odmawia. | Dlaczego Bolek nie powinien lub nie może odpowiedzieć, np. prośba o coś, czego Bolek nie potrafi, jak rezerwacja podróży |

Nie zapisuj przyczyn, takich jak pominięty dokument czy nieaktualne źródło: w etapie 1 ich nie widać.

## Waga

Ustaw wagę tylko wtedy, gdy zapisujesz kod; bez kodu zostaw ją pustą.

| Poziom | Znaczenie |
|---|---|
| `HIGH` | Kluczowe twierdzenie przy intencji wiedzy jest sprzeczne z dowodami (`CONTRADICTED_CLAIM`). Nic innego nie jest `HIGH`. |
| `MEDIUM` | Odpowiedź nie spełnia celu bez sprzeczności: niepoparte kluczowe twierdzenie, brak głównej części, źle zrozumiane pytanie, błąd narzędzia albo pytanie wewnętrzne bez dowodów. |
| `LOW` | Użytkownik i tak dostaje to, czego potrzebuje: problem z formatowaniem lub językiem, drobna luka. |

## Pewność

Twoja pewność co do całego formularza, od 0 do 1. Służy tylko do informacji.

## Przykłady (dokumenty i liczby są zmyślone)

| Tura | Intencja | Trafność | Kompletność | Jasność | Ugruntowanie | Błąd, waga |
|---|---|---|---|---|---|---|
| „Ile mam dni urlopu na żądanie?” Źródło mówi: do 4; odpowiedź mówi: 6. | `FACT_LOOKUP` | 5 | 5 | 5 | 1 | `CONTRADICTED_CLAIM`, `HIGH` |
| „Jak zarezerwować podróż służbową i kto ją zatwierdza?” Odpowiedź wyjaśnia tylko rezerwację, co źródło potwierdza. | `HOW_TO` | 5 | 3 | 5 | 5 | `INCOMPLETE_ANSWER`, `MEDIUM` |
| „Jaki jest limit?”, bez wcześniejszych tur. Odpowiedź obszernie opisuje limity wydatków na posiłki. | `OTHER` | 2 | 2 | 4 | (nie pytamy) | `AMBIGUOUS_QUESTION`, `MEDIUM` |

W pierwszym przykładzie trafność zostaje 5: odpowiedź jest na temat, tylko błędna. W drugim brakująca część obniża
kompletność, nie trafność. Dlatego każde pole ocenia się osobno. W trzecim Bolek powinien był zapytać, o który limit
chodzi; zgadywanie minęło się z pytaniem, więc użytkownik nie dostał tego, czego potrzebował.
