"""Recall of the PII scrubber on synthetic Polish and English text with planted personal details (§6.12, §12.13)."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from conversation_analyzer.pii.scrubber import Analyzer, PiiMap, default_analyzer, scrub

EVAL_SET = Path(__file__).with_name("eval_set.yaml")
_PERSON = re.compile(r"^<PERSON_\d+>$")


def evaluate(analyzer: Analyzer | None = None, path: Path = EVAL_SET) -> dict[str, Any]:
    """Planted values found per language and type, persons with one placeholder for all forms, kept content words."""
    analyzer = analyzer or default_analyzer()
    planted: Counter[tuple[str, str]] = Counter()
    found: Counter[tuple[str, str]] = Counter()
    missed: list[tuple[str, str]] = []
    persons = consistent = documents = documents_ok = keep = kept = 0
    for conv in yaml.safe_load(path.read_text()):
        lang = conv["language"] + ("-held-out" if conv.get("held_out") else "")
        pii = PiiMap()
        for item in conv["texts"]:
            out = scrub(item["text"], pii, analyzer)
            for entity_type, value in item.get("planted", []):
                planted[(lang, entity_type)] += 1
                if value in out:
                    missed.append((entity_type, value))
                else:
                    found[(lang, entity_type)] += 1
            for word in item.get("keep", []):
                keep += 1
                kept += word in out
        placeholders = {}
        for person, forms in conv.get("persons", {}).items():
            persons += 1
            seen = {pii.apply(f) for f in forms}
            placeholders[person] = next(iter(seen))
            consistent += len(seen) == 1 and bool(_PERSON.match(placeholders[person]))
        for doc in conv.get("documents", []):
            documents += 1
            applied = pii.apply(doc)
            documents_ok += all(
                placeholders[p] in applied and not any(f in applied for f in forms)
                for p, forms in conv.get("persons", {}).items()
                if any(f in doc for f in forms)
            )
    by_type = [
        {"language": lang, "type": t, "planted": n, "found": found[(lang, t)], "recall": round(found[(lang, t)] / n, 3)}
        for (lang, t), n in sorted(planted.items())
    ]
    total = sum(planted.values())
    return {
        "recall": round(sum(found.values()) / total, 3) if total else None,
        "by_type": by_type,
        "missed": missed,
        "persons_consistent": (consistent, persons),
        "documents_consistent": (documents_ok, documents),
        "content_kept": (kept, keep),
    }


def main() -> None:  # pragma: no cover - prints the measurement of the real scrubber
    report = evaluate()
    print(f"{'language':12} {'type':14} {'planted':>7} {'found':>6} {'recall':>7}")
    for r in report["by_type"]:
        print(f"{r['language']:12} {r['type']:14} {r['planted']:7} {r['found']:6} {r['recall']:7.3f}")
    print(f"overall recall {report['recall']}")
    for label, (ok, n) in (
        ("persons with one placeholder for all forms", report["persons_consistent"]),
        ("documents with the conversation's placeholders", report["documents_consistent"]),
        ("content words kept", report["content_kept"]),
    ):
        print(f"{label}: {ok}/{n}")
    for entity_type, value in report["missed"]:  # synthetic values only
        print(f"missed {entity_type}: {value}")


if __name__ == "__main__":
    main()
