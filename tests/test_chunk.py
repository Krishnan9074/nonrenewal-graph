from extraction_service.chunk import split


def test_short_text_single_chunk():
    assert split("abc") == [split("abc")[0]] and split("abc")[0].text == "abc"


def test_chunks_cover_text_with_overlap():
    text = "\n".join(f"line {i} " + "x" * 80 for i in range(400))
    chunks = split(text, target=5000, overlap=500)
    assert chunks[0].start == 0
    assert chunks[-1].start + len(chunks[-1].text) == len(text)
    assert all(n.start < p.start + len(p.text) for p, n in zip(chunks, chunks[1:], strict=False))
