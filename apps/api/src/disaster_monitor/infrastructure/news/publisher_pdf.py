"""Extract bounded plain text from publisher PDFs in an isolated worker."""

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader

MAX_PDF_BYTES = 12 * 1024**2
_MAX_PAGES = 128
_MAX_TEXT = 20_000
_WORKER_TIMEOUT = 10
_PROSE_WRAP = re.compile(r"(?<=[^.!?:;\s])[ \t]+\r?\n(?=[a-zà-öø-ÿ])")
_TEXT_BOUNDARY = re.compile(r"[.!?](?=\s)|\n")
_LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"})


@dataclass(frozen=True, slots=True)
class PublisherPdfText:
    text: str
    imprint: str
    title: str


async def extract_publisher_pdf(body: bytes) -> PublisherPdfText:
    if len(body) > MAX_PDF_BYTES or not body.startswith(b"%PDF-"):
        raise ValueError("Invalid or oversized publisher PDF.")
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        __name__,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(_WORKER_TIMEOUT):
            extracted, _ = await worker.communicate(body)
    except TimeoutError as error:
        raise ValueError("Publisher PDF exceeded its parsing time limit.") from error
    finally:
        if worker.returncode is None:
            try:
                worker.kill()
            except ProcessLookupError:
                pass
            await worker.communicate()
    if worker.returncode != 0:
        raise ValueError("Publisher PDF could not be read within parsing limits.")
    data = json.loads(extracted)
    return PublisherPdfText(data["text"], data["imprint"], data["title"])


def _read_text(body: bytes) -> PublisherPdfText:
    reader = PdfReader(BytesIO(body))
    if reader.is_encrypted or len(reader.pages) > _MAX_PAGES:
        raise ValueError("Encrypted or oversized publisher PDF.")
    pages = []
    imprint = []
    remaining = _MAX_TEXT
    for page in reader.pages:
        raw = page.extract_text().translate(_LIGATURES)
        if len(imprint) < 2:
            imprint.append(
                raw[:_MAX_TEXT].rpartition("\n")[0] if len(raw) > _MAX_TEXT else raw
            )
        # pypdf preserves trailing space at some wrapped prose lines. Leave
        # labels, sentence boundaries, page breaks and other rows in place.
        text = _PROSE_WRAP.sub(" ", raw).strip()
        if len(text) > remaining:
            end = max(
                (match.end() for match in _TEXT_BOUNDARY.finditer(text, 0, remaining)),
                default=0,
            )
            pages.append(text[:end].rstrip())
            break
        pages.append(text)
        remaining -= len(text) + 2
        if remaining <= 0:
            break
    title = (reader.metadata.title or "") if reader.metadata else ""
    return PublisherPdfText(
        "\n\n".join(pages)[:_MAX_TEXT],
        "\n".join(imprint),
        " ".join(title.split())[:300],
    )


def _main() -> None:
    import resource

    # Page and byte limits do not bound decompressed PDF object graphs.
    memory = 384 * 1024**2
    resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
    body = sys.stdin.buffer.read(MAX_PDF_BYTES + 1)
    if len(body) > MAX_PDF_BYTES or not body.startswith(b"%PDF-"):
        raise ValueError("Invalid or oversized publisher PDF.")
    output = _read_text(body)
    json.dump(
        {"text": output.text, "imprint": output.imprint, "title": output.title},
        sys.stdout,
        ensure_ascii=True,
    )


if __name__ == "__main__":
    _main()
