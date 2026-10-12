"""Readable plain text for Somtoday HTML descriptions."""

from html.parser import HTMLParser
import re


class _PlainText(HTMLParser):
    """Render rich source text without markup or executable content."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0
        self.has_markup = False
        self.lists = []

    def handle_starttag(self, tag, attrs):
        self.has_markup = True
        if tag in {"script", "style"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in {"p", "div", "br", "li", "ul", "ol", "tr"}:
            self.parts.append("\n")
        if tag in {"ol", "ul"}:
            self.lists.append([tag, 0])
        if tag == "li":
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                self.parts.append(f"{self.lists[-1][1]}. ")
            else:
                self.parts.append("• ")
        if tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        self.has_markup = True
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "li", "ul", "ol", "tr"}:
            self.parts.append("\n")
        if not self.hidden and tag in {"ol", "ul"} and self.lists:
            self.lists.pop()

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(value):
    """Decode HTML once and keep readable, non-empty lines."""
    parser = _PlainText()
    parser.feed(str(value or ""))
    parser.close()
    lines = [re.sub(r"[^\S\n]+", " ", line).strip()
             for line in "".join(parser.parts).splitlines()]
    if not parser.has_markup:
        return "\n".join(lines).strip()
    return "\n".join(line for line in lines if line)

