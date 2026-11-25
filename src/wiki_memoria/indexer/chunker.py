import re
from typing import NamedTuple


class Chunk(NamedTuple):
    section_heading: str
    section_index: int
    content: str


class MarkdownChunker:
    def chunk(self, text: str) -> list[Chunk]:
        result = []
        heading = ""
        start = 0
        for match in re.finditer(r"(?m)^#{1,3}[ \t]+(.+)$", text):
            self._append(result, heading, text[start:match.start()])
            heading, start = match[1].strip(), match.start()
        self._append(result, heading, text[start:])
        return result

    @staticmethod
    def _append(result: list[Chunk], heading: str, section: str) -> None:
        section = section.strip()
        for pos in range(0, len(section), 1200):
            result.append(Chunk(heading, len(result), section[pos:pos + 1200]))
