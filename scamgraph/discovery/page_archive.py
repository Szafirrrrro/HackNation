"""Local references for one browser DOM and its captured stylesheets."""
import hashlib
import mimetypes
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit

import tinycss2
from tinycss2.bytes import decode_stylesheet_bytes
from tinycss2.serializer import serialize_string_value


def asset_name(url, mime, body):
    kind = mime.partition(";")[0].strip().lower()
    suffix = {"application/javascript": ".js", "application/x-javascript": ".js",
               "text/javascript": ".js", "image/jpeg": ".jpg"}.get(kind)
    suffix = suffix or mimetypes.guess_extension(kind) or ".bin"
    return hashlib.sha256(url.encode() + b"\0" + body).hexdigest()[:32] + suffix


def rewrite_css(source, base, local, prefix):
    def resolve(value):
        try:
            if not value or value.startswith("#") or urlsplit(value).scheme in {"data", "blob"}:
                return value
            absolute, fragment = urldefrag(urljoin(base, value))
        except ValueError:
            return value
        mapped = prefix + local[absolute] if absolute in local else absolute
        return mapped + ("#" + fragment if fragment else "")

    def string(value):
        return '"' + serialize_string_value(value) + '"'

    def visit(tokens):
        after_import = False
        for token in tokens:
            if token.type in {"whitespace", "comment"}:
                continue
            if token.type == "url":
                token.representation = "url(" + string(resolve(token.value)) + ")"
            elif token.type == "function" and token.lower_name == "url":
                args = [a for a in token.arguments if a.type not in {"whitespace", "comment"}]
                if len(args) == 1 and args[0].type == "string":
                    args[0].representation = string(resolve(args[0].value))
            elif token.type == "string" and after_import:
                token.representation = string(resolve(token.value))
            elif hasattr(token, "content"):
                visit(token.content)
            elif hasattr(token, "arguments"):
                visit(token.arguments)
            after_import = token.type == "at-keyword" and token.lower_value == "import"

    tokens = tinycss2.parse_component_value_list(source)
    visit(tokens)
    return tinycss2.serialize(tokens)


def save_dom(page, directory, input_url, local, styles, issues):
    for name, (base, body, charset) in styles.items():
        source, encoding = decode_stylesheet_bytes(body, protocol_encoding=charset)
        try:
            css = rewrite_css(source, base, local, "./")
            data = css.encode(encoding.codec_info.name, "backslashreplace")
        except (ValueError, TypeError, RecursionError):
            data = body
            issues.add("Zachowano arkusz CSS z odwołaniami w pierwotnej postaci.")
        (directory / "page_files" / name).write_bytes(data)
    base, values = page.evaluate("""() => [document.baseURI, [...new Set([
        ...Array.from(document.querySelectorAll('[style]'), n=>n.getAttribute('style')),
        ...Array.from(document.querySelectorAll('style'), n=>n.textContent)])]]""")
    inline = {}
    for value in values:
        try:
            inline[value] = rewrite_css(value, base, local, "./page_files/")
        except (ValueError, TypeError, RecursionError):
            issues.add("Zachowano styl wewnętrzny z odwołaniami w pierwotnej postaci.")
    script = Path(__file__).with_name("snapshot.js").read_text(encoding="utf8")
    html = page.evaluate(script, {"local": local, "inline": inline})
    comment = input_url.replace("--", "%2D%2D").replace(">", "%3E")
    temp = directory / "page.html.tmp"
    temp.write_text(f"<!-- Original URL: {comment} -->\n" + html, encoding="utf8")
    temp.replace(directory / "page.html")
