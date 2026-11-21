"""Readable transcript in DOM order, retaining locations and the interface separately."""
from pathlib import Path
import re

from .sources import clean, digest, evidence, fact


BLOCK = set("address article aside blockquote body caption dd details div dl dt figcaption footer h1 h2 h3 h4 h5 h6 header li main nav p section small table td th tr ul ol".split())
INTERFACE = {"nav", "header", "footer", "form", "button"}


def consent_candidate(node):
    return (node.attr("role") in {"dialog", "alertdialog"} or node.attr("aria-modal") == "true" or
            (node.attr("role") == "region" and re.search(
                r"cookiebotdialog|onetrust-banner|(?:cookie|consent)[_-]?(?:banner|dialog|modal)",
                node.attr("id") + " " + node.attr("class"), re.I)))


def transcript(doc, artifact, dialog_ids):
    rows = []
    buffer = []
    positions = []
    current = None

    def flush():
        value = clean("".join(buffer))
        buffer.clear()
        if value and current:
            node, section = current
            rows.append({"section": section, **fact(value, evidence(artifact, element=node.index, tag=node.tag,
                        line=node.line, text_parts=positions.copy()))})
        positions.clear()

    stack = [(doc.root, doc.root, False, enumerate(doc.root.parts))]
    while stack:
        node, block, interface, parts = stack[-1]
        for i, part in parts:
            if isinstance(part, str):
                key = (block, "interface" if interface else "content")
                if current != key:
                    flush()
                    current = key
                buffer.append(part)
                positions.append([node.index, i])
            elif part.tag == "br":
                flush()
            elif not part.hidden() and part.tag not in {"head", "title"}:
                chrome = (interface or part.tag in INTERFACE or part.index in dialog_ids or
                          part.attr("role") in {"navigation", "menu", "banner", "contentinfo"})
                stack.append((part, part if part.tag in BLOCK else block, chrome, enumerate(part.parts)))
                break
        else:
            stack.pop()
    flush()
    return rows


def text_exports(folder, pages, artifacts):
    exports = []
    occupied = {a["path"].casefold() for a in artifacts}
    for i, page in enumerate(pages, 1):
        rows = page.get("reading_text", [])
        if not rows:
            continue
        name = "landing/page.txt" if len(pages) == 1 else f"landing/page-{i}.txt"
        while name.casefold() in occupied:
            name = str(Path(name).with_suffix(".extracted.txt")).replace("\\", "/")
        occupied.add(name.casefold())
        chunks = []
        for section, heading in (("content", "Treść strony"), ("interface", "Nawigacja i komunikaty strony")):
            lines = [r["value"] for r in rows if r["section"] == section]
            if lines:
                chunks.append(heading + "\n\n" + "\n".join(lines))
        dest = folder / name
        dest.write_text("\n\n".join(chunks) + "\n", encoding="utf8")
        item = {"path": name, "role": "page_text", "type": "text/plain", "sha256": digest(dest),
                "size": dest.stat().st_size, "source": page.get("reading_source", page["evidence"])}
        exports.append(item)
    return exports
