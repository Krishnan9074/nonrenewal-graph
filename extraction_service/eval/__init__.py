import json
from pathlib import Path

from extraction_service.adapters import build
from extraction_service.models import Extraction
from extraction_service.worker import MODEL_ID, process

GOLDEN = Path(__file__).parent / "golden"


def keys(x: Extraction) -> set[tuple]:
    return {(e.src_mention.strip().lower(), e.rel, e.dst_mention.strip().lower()) for e in x.edges}


def main() -> None:
    adapter = build(MODEL_ID)
    tp = fp = fn = 0
    for case in sorted(GOLDEN.glob("*.json")):
        g = json.loads(case.read_text())
        pred, gold = (
            keys(process(g["doc_id"], g["text"], adapter)),
            keys(Extraction.model_validate(g["expected"])),
        )
        tp, fp, fn = tp + len(pred & gold), fp + len(pred - gold), fn + len(gold - pred)
    print(f"precision={tp / max(tp + fp, 1):.3f} recall={tp / max(tp + fn, 1):.3f} tp={tp} fp={fp} fn={fn}")


if __name__ == "__main__":
    main()
