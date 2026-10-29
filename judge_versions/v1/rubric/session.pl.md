# Rubryka oceny sesji (po polsku)

Oceniasz cały segment sesji: czy użytkownik dostał to, czego potrzebował, a jeśli nie, gdzie poszło źle. Widzisz
tekst wszystkich tur segmentu wraz z wynikami etapów 1 i 2. Potrzeba użytkownika to to, co chciał uzyskać z całego
segmentu, a nie z jednej tury.

| Wynik | Znaczenie |
|---|---|
| `RESOLVED` | Do końca segmentu użytkownik dostał to, czego potrzebował: ostatnia odpowiedź na jego potrzebę jest trafna i nie ma problemu `MEDIUM` ani `HIGH`, a użytkownik jej potem nie poprawiał ani nie okazał frustracji. Wcześniejsze złe odpowiedzi są dopuszczalne, jeśli późniejsza je naprawiła. |
| `PARTIALLY_RESOLVED` | Użytkownik miał kilka potrzeb lub potrzebę z kilkoma częściami i do końca spełniono tylko niektóre. |
| `UNRESOLVED` | Potrzeba nie została spełniona do końca: ostatnia odpowiedź na nią ma problem `MEDIUM` lub `HIGH` albo użytkownik ją poprawił lub okazał po niej frustrację. |
| `UNCLEAR` | Nie da się ustalić, czego użytkownik potrzebował ani czy to dostał, np. gdy segment kończy się zaraz po odpowiedzi, której nie da się sprawdzić. |

| Pole | Jak je ustawić |
|---|---|
| Pierwsza zła tura | Pozycja pierwszej tury ze zidentyfikowanym problemem o wadze `MEDIUM` lub `HIGH` albo pierwszej, którą użytkownik poprawił. Pusta, gdy nic nie poszło źle. |
| Naprawione po korekcie | `NO_CORRECTION`, gdy użytkownik nigdy nie poprawił odpowiedzi. W przeciwnym razie `YES`, gdy po pierwszej korekcie użytkownika późniejsza odpowiedź dała to, o co pytał, bez zidentyfikowanego problemu; inaczej `NO`. |
| Pewność | Od 0 do 1, tylko do informacji. |

## Przykładowe segmenty (zmyślone)

| Segment | Wynik | Pierwsza zła tura | Naprawione |
|---|---|---|---|
| 1: „Ile dni urlopu na żądanie?” odpowiedź 6 (sprzeczna). 2: „To błąd, to 4.” odpowiedź: „Masz rację, 4 dni.” | `RESOLVED` | 1 | `YES` |
| 1: „Jak zarezerwować podróż i kto ją zatwierdza?” odpowiedź tylko o rezerwacji. 2: „A zatwierdzenie?” odpowiedź nie na temat. 3: „Nieważne.” | `UNRESOLVED` | 1 | `NO_CORRECTION` |
| 1: „Polityka urlopowa i limity wydatków?” dobra odpowiedź tylko o urlopie. | `PARTIALLY_RESOLVED` | 1 | `NO_CORRECTION` |
