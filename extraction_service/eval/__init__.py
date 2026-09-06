import json
from collections import Counter
from pathlib import Path

from extraction_service.adapters import build
from extraction_service.models import Extraction
from extraction_service.worker import MODEL_ID, process

GOLDEN = Path(__file__).parent / "golden"


def keys(x: Extraction) -> set[tuple]:
    return {(e.src_mention.strip().lower(), e.rel, e.dst_mention.strip().lower()) for e in x.edges}


def prf(tp: int, fp: int, fn: int) -> str:
    return f"precision={tp / max(tp + fp, 1):.3f} recall={tp / max(tp + fn, 1):.3f} tp={tp} fp={fp} fn={fn}"


def main() -> None:
    adapter = build(MODEL_ID)
    total, by_rel = Counter(), {}
    for case in sorted(GOLDEN.glob("*.json")):
        g = json.loads(case.read_text())
        art = process(g["doc_id"], g["text"], adapter)
        pred, gold = keys(art), keys(Extraction.model_validate(g["expected"]))
        c = Counter(tp=len(pred & gold), fp=len(pred - gold), fn=len(gold - pred))
        total += c
        for rel in {k[1] for k in pred | gold}:
            r = by_rel.setdefault(rel, Counter())
            r.update(tp=len({k for k in pred & gold if k[1] == rel}), fp=len({k for k in pred - gold if k[1] == rel}))
            r.update(fn=len({k for k in gold - pred if k[1] == rel}))
        print(f"{case.stem:28} {prf(c['tp'], c['fp'], c['fn'])}  rejected={len(art.rejected)}")
        for k in sorted(pred - gold)[:5]:
            print(f"    fp {k}")
        for k in sorted(gold - pred)[:5]:
            print(f"    fn {k}")
    for rel, c in sorted(by_rel.items()):
        print(f"{rel:28} {prf(c['tp'], c['fp'], c['fn'])}")
    print(f"{'ALL':28} {prf(total['tp'], total['fp'], total['fn'])}")


if __name__ == "__main__":
    main()
