from dataclasses import dataclass

TARGET, OVERLAP = 12000, 1200  # a CDI bulletin is ~6k chars; keep its ZIP lists and declaration date in one chunk


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
