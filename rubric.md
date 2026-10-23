# Stage 1 rubric (draft)

| | |
|---|---|
| Used by | `design-doc.md` §5.4 (the form), `design.md` D12 |
| Version | `rubric_version` = `r0-draft`. Not yet tuned on the canary. |
| Status | Draft, 2026-10-23. Level texts written for all five levels in English and Polish. The examples are placeholders, to be replaced by examples built from canary and evaluator turns. |

The rubric tells the judge what each score level means. The judge gets the rubric text in both languages, plus the example turns, with every stage 1 call.

## 1. Why the boundaries matter

Two thresholds turn scores into decisions, so the rubric has to be sharpest at levels 2 and 4:

| Score | Means for the turn |
|---|---|
| Relevance or groundedness **2 or lower** | The turn is flagged for stage 2. |
| Relevance **4 or higher**, and groundedness **4 or higher** (knowledge intents) | Needed for a good answer, which also requires no `HIGH` severity. |

So **3 is the "neither" level**. The answer is not bad enough to flag, and not good enough to count as good.

## 2. General rules for the judge

| English | Polski |
|---|---|
| Judge only against what you are given: the question, the answer, the earlier turns and the evidence. You do not know what is true at the company. | Oceniaj wyłącznie na podstawie tego, co otrzymujesz: pytania, odpowiedzi, wcześniejszych tur i dowodów. Nie wiesz, co jest prawdą w firmie. |
| A claim is wrong only when the evidence says something different. If the evidence says nothing about it, the claim is unsupported, not wrong. | Twierdzenie jest błędne tylko wtedy, gdy dowody mówią coś innego. Jeśli dowody nic o nim nie mówią, twierdzenie jest niepoparte, a nie błędne. |
| Between two levels, choose the lower one only if you can name the concrete defect that rules out the higher one. Otherwise choose the higher one. | Gdy wahasz się między dwoma poziomami, wybierz niższy tylko wtedy, gdy potrafisz wskazać konkretną wadę, która wyklucza wyższy. W przeciwnym razie wybierz wyższy. |
| Score each field on its own. A clear answer can be wrong, and a correct one can be hard to read. | Każde pole oceniaj osobno. Jasna odpowiedź może być błędna, a poprawna może być trudna w odbiorze. |
| Leave out fields that do not apply to the intent. Do not guess them. | Pomiń pola, które nie dotyczą danej intencji. Nie zgaduj ich wartości. |
| Answers may be in Polish or English. Judge the content, not the language, unless the answer's language differs from the question's. | Odpowiedzi mogą być po polsku lub po angielsku. Oceniaj treść, nie język, chyba że język odpowiedzi różni się od języka pytania. |

A **key claim** is one the user would act on: a number, name, date, rule, step, place or link. *Kluczowe twierdzenie* to takie, na podstawie którego użytkownik podejmie działanie: liczba, nazwa, data, zasada, krok, miejsce lub link.

## 3. Relevance: does it answer this question?

| Level | English | Polski |
|---|---|---|
| **5** | Answers exactly the question asked, directly, at the start. | Odpowiada dokładnie na zadane pytanie, wprost i od razu. |
| **4** | Answers the question, but with a detour or material the user did not need. | Odpowiada na pytanie, ale z dygresją lub treścią, której użytkownik nie potrzebował. |
| **3** | Partly on target. It answers a broader or related question, and the user has to dig out the answer. | Częściowo trafia. Odpowiada na pytanie szersze lub pokrewne, a użytkownik musi sam wyłuskać odpowiedź. |
| **2** | Mostly off target. It is about the topic, not the question. | W większości nie na temat. Dotyczy tematu, a nie pytania. |
| **1** | Does not answer the question: it answers a different one, refuses without a reason, or is empty. | Nie odpowiada na pytanie: odpowiada na inne, odmawia bez powodu albo jest pusta. |

- A justified refusal of an out-of-scope question, with a short reason, is **4**. *Uzasadniona odmowa przy pytaniu spoza zakresu, z krótkim wyjaśnieniem, to 4.*
- A clarifying question back, when the question really is ambiguous, is **4**. *Dopytanie, gdy pytanie jest naprawdę niejednoznaczne, to 4.*

## 4. Completeness: does it cover every part of the question?

| Level | English | Polski |
|---|---|---|
| **5** | Covers every part of the question, with what the user needs to act: steps, conditions, exceptions. | Obejmuje każdą część pytania, z tym, czego użytkownik potrzebuje, by działać: krokami, warunkami, wyjątkami. |
| **4** | Covers every part. A minor detail is missing, and the user can do without it. | Obejmuje każdą część. Brakuje drobnego szczegółu, bez którego użytkownik się obejdzie. |
| **3** | One part of a multi-part question is missing, or the main part lacks a condition or step the user needs. | Brakuje jednej części pytania złożonego albo w głównej części brakuje warunku lub kroku, którego użytkownik potrzebuje. |
| **2** | Only a small part of the question is answered. | Odpowiedziano tylko na niewielką część pytania. |
| **1** | Nothing of substance is answered. | Brak jakiejkolwiek merytorycznej odpowiedzi. |

Completeness is about the question, not about the documents. Leaving out document content the user did not ask for is not a defect. *Kompletność dotyczy pytania, nie dokumentów. Pominięcie treści dokumentu, o którą nie pytano, nie jest wadą.*

## 5. Clarity: is it easy to read and use?

| Level | English | Polski |
|---|---|---|
| **5** | Easy to read and use at once. The answer comes first, the structure fits the content, and formatting works. | Łatwa do przeczytania i od razu użyteczna. Odpowiedź jest na początku, struktura pasuje do treści, formatowanie działa. |
| **4** | Clear, but longer or less ordered than needed. | Jasna, ale dłuższa lub mniej uporządkowana, niż trzeba. |
| **3** | Usable with effort: wordy, poorly ordered, or with unexplained jargon. | Użyteczna, ale wymaga wysiłku: rozwlekła, źle uporządkowana albo z niewyjaśnionym żargonem. |
| **2** | Hard to follow: confusing, mixing languages, or broken formatting that hides content. | Trudna do zrozumienia: chaotyczna, mieszająca języki albo z zepsutym formatowaniem, które ukrywa treść. |
| **1** | Unusable: unreadable, in the wrong language throughout, or broken output. | Bezużyteczna: nieczytelna, w całości w złym języku albo z uszkodzoną treścią. |

## 6. Groundedness: is it supported by its evidence?

Verifiable turns of knowledge intents only. Where the log splits the answer into answer spans, check each span against the references it points to, and fill in the two answer span counts. The counts guide the score, but there is no formula: one unsupported key claim weighs more than several unsupported side remarks.

*Tylko tury weryfikowalne o intencjach wiedzowych. Jeśli log dzieli odpowiedź na fragmenty, sprawdź każdy fragment względem źródeł, na które wskazuje, i wypełnij oba liczniki fragmentów. Liczniki pomagają w ocenie, ale nie ma wzoru: jedno niepoparte kluczowe twierdzenie waży więcej niż kilka niepopartych uwag pobocznych.*

| Level | English | Polski |
|---|---|---|
| **5** | Every claim is supported by the evidence. | Każde twierdzenie jest poparte dowodami. |
| **4** | Every key claim is supported. Only side remarks or general knowledge lack support. | Każde kluczowe twierdzenie jest poparte. Brak poparcia dotyczy tylko uwag pobocznych lub wiedzy ogólnej. |
| **3** | Most key claims are supported, but at least one is not. Nothing is contradicted. | Większość kluczowych twierdzeń jest poparta, ale co najmniej jedno nie jest. Nic nie jest sprzeczne z dowodami. |
| **2** | Most key claims are unsupported, **or** one key claim is contradicted by the evidence. | Większość kluczowych twierdzeń jest niepoparta **albo** jedno kluczowe twierdzenie jest sprzeczne z dowodami. |
| **1** | The answer as a whole is not backed by its evidence, or its main point is contradicted. | Odpowiedź jako całość nie jest poparta dowodami albo jej główna teza jest z nimi sprzeczna. |

A contradicted key claim always means **groundedness 2 or lower**, failure `CONTRADICTED_CLAIM`, and severity `HIGH`. *Sprzeczne kluczowe twierdzenie zawsze oznacza ugruntowanie 2 lub niżej, błąd `CONTRADICTED_CLAIM` i wagę `HIGH`.*

## 7. Severity

Set only when there is an identified failure. With `NONE`, severity is left empty.

| Level | English | Polski |
|---|---|---|
| **HIGH** | A key claim on a knowledge intent is contradicted by the evidence (`CONTRADICTED_CLAIM`). Nothing else is `HIGH`. | Kluczowe twierdzenie przy intencji wiedzowej jest sprzeczne z dowodami (`CONTRADICTED_CLAIM`). Nic innego nie jest `HIGH`. |
| **MEDIUM** | The answer fails its purpose without a contradiction: an unsupported key claim, a missing main part, a misunderstood question, a tool error, or an internal question answered with no sources. | Odpowiedź nie spełnia swojego celu, choć nie ma sprzeczności: niepoparte kluczowe twierdzenie, brak głównej części, źle zrozumiane pytanie, błąd narzędzia albo pytanie o wiedzę wewnętrzną bez źródeł. |
| **LOW** | The user still gets what they need: a formatting or language problem, a minor gap. | Użytkownik i tak dostaje to, czego potrzebuje: problem z formatowaniem lub językiem, drobna luka. |

## 8. Example turns (placeholders)

These examples are **made up** to show the format. The documents and numbers are fictional. They will be replaced by examples built from canary and evaluator turns, at least one per intent and one per failure type, in both languages.

### E1. Good answer (English, `FACT_LOOKUP`)

- **Question:** How many days of remote work abroad are allowed per year?
- **Reference:** *Remote work policy (fictional):* "Employees may work remotely from abroad for up to 30 days per calendar year, with manager approval."
- **Answer:** "Up to 30 days per calendar year, and your manager has to approve it." One answer span, pointing to the reference.

| Relevance | Completeness | Clarity | Groundedness | Spans | Failure | Severity |
|---|---|---|---|---|---|---|
| 5 | 5 | 5 | 5 | 0 of 1 unsupported | `NONE` | (empty) |

### E2. Contradicted claim (Polish, `FACT_LOOKUP`)

- **Pytanie:** Ile dni urlopu na żądanie przysługuje w roku?
- **Źródło:** *Regulamin urlopów (fikcyjny):* „Pracownik może wykorzystać do 4 dni urlopu na żądanie w roku kalendarzowym."
- **Odpowiedź:** „Przysługuje Ci 6 dni urlopu na żądanie w roku." One answer span, pointing to the reference.

| Relevance | Completeness | Clarity | Groundedness | Spans | Failure | Severity |
|---|---|---|---|---|---|---|
| 5 | 5 | 5 | 1 | 1 of 1 unsupported | `CONTRADICTED_CLAIM` | `HIGH` |

Relevance stays 5: the answer is on target, just wrong. That is why the fields are scored separately.

### E3. Incomplete answer (English, `HOW_TO`)

- **Question:** How do I book a business trip, and who approves it?
- **Reference:** *Travel booking guide (fictional):* "Book through the travel portal. Trips are approved by your manager; trips outside Europe also need finance approval."
- **Answer:** "Book it through the travel portal." One answer span, supported.

| Relevance | Completeness | Clarity | Groundedness | Spans | Failure | Severity |
|---|---|---|---|---|---|---|
| 4 | 3 | 5 | 5 | 0 of 1 unsupported | `INCOMPLETE_ANSWER` | `MEDIUM` |

The approval part of the question is missing entirely, so completeness is 3 and severity `MEDIUM`.

### E4. No evidence (Polish, `HOW_TO`, not verifiable)

- **Pytanie:** Jak zgłosić zmianę konta bankowego do wypłaty?
- **Źródła:** brak, ani w tej turze, ani we wcześniejszych.
- **Odpowiedź:** „Zmianę zgłoś w systemie kadrowym w zakładce Dane osobowe."

| Relevance | Completeness | Clarity | Groundedness | Spans | Failure | Severity |
|---|---|---|---|---|---|---|
| 5 | 4 | 5 | (empty) | (empty) | `UNGROUNDED_INTERNAL_ANSWER` | `MEDIUM` |

Needs internal knowledge, no references: the code is deterministic. Then the evidence check runs. If a document found by search says something different, `CONTRADICTED_CLAIM` and `HIGH` are added. Otherwise nothing more is recorded.

### E5. Guess instead of asking back (English, `OTHER`)

- **Question:** What's the limit?
- **Earlier turns:** none.
- **Answer:** A long explanation of meal expense limits.

| Relevance | Completeness | Clarity | Groundedness | Spans | Failure | Severity |
|---|---|---|---|---|---|---|
| 2 | 2 | 4 | (not asked) | (not asked) | `AMBIGUOUS_QUESTION` | `LOW` |

Bolek should have asked which limit was meant. The same question answered with "Which limit do you mean: expenses, leave or something else?" would be relevance 4 and `NONE`.

### E6. Not a knowledge question (English, `GENERAL_TASK`)

- **Question:** Make this paragraph shorter and more polite: (pasted text)
- **Answer:** A shorter, polite version of the paragraph.

| Relevance | Completeness | Clarity | Groundedness | Spans | Failure | Severity |
|---|---|---|---|---|---|---|
| 5 | 5 | 5 | (not asked) | (not asked) | `NONE` | (empty) |

Groundedness does not apply to this intent.

## 9. Not decided yet

- **Polish text review** by a native speaker on the team, mainly for terms like *ugruntowanie* (groundedness) and *kluczowe twierdzenie* (key claim).
- **Tuning on the canary:** whether the level texts give stable scores. Each level text changes `rubric_version`, and a change starts the 5-weekday parallel run.
- **The bar for "identified"** on non-deterministic codes such as `INCOMPLETE_ANSWER` and `MISUNDERSTOOD_QUERY` (Q12).
- **Severity of `UNGROUNDED_INTERNAL_ANSWER`**: `MEDIUM` here, because the user can't check the answer. It could be argued as `LOW` when the evidence check finds nothing against it.
- **The session grade rubric** belongs with stage 2: outcome meanings are proposed in `design-doc.md` §6.6, to be translated and given examples here.
