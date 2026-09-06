from html.parser import HTMLParser

BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "ul", "ol", "tr", "hr"}
SKIP = {"script", "style"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in SKIP:
            self.skip += 1
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP:
            self.skip -= 1
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def to_text(html: str, start: str = "<H1>", end: str = 'class="content_right_column') -> str:
    """CDI pages wrap the release in a left column between the headline and the sidebar; fail if either marker is missing."""
    i, j = html.find(start), html.find(end)
    if i < 0 or j < i:
        raise ValueError(f"html_text: markers {start!r}..{end!r} not found")
    p = _Text()
    p.feed(html[i:j])
    lines = (" ".join(line.split()) for line in "".join(p.parts).splitlines())
    return "\n".join(line for line in lines if line)
