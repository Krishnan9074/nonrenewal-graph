from dataclasses import dataclass

TARGET, OVERLAP = 5000, 1500  # ~10 fires per chunk: the model drops ZIPs past ~200 per call; overlap covers a whole ZIP list
HEAD = 3500  # the document head travels with every chunk as context: bulletins date their declarations on page 2-3


@dataclass(frozen=True)
class Chunk:
    idx: int
    start: int
    text: str


def split(text: str, target: int = TARGET, overlap: int = OVERLAP) -> list[Chunk]:
    if len(text) <= target:
        return [Chunk(0, 0, text)]
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + target)
        if end < len(text) and (cut := text.rfind("\n", start + target // 2, end)) > 0:
            end = cut
        chunks.append(Chunk(len(chunks), start, text[start:end]))
        if end == len(text):
            break
        start = end - overlap
    return chunks
