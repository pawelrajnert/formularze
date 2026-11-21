"""C-03: DOCX (python-docx), XLSX (openpyxl), DOC/ODS (LibreOffice -> DOCX/XLSX -> jak wyżej).

DOCX: akapity i tabele w kolejności dokumentu, pola tekstowe (textbox) bez dublowania mc:Fallback,
pola wyboru -> ☐/☒. Komórki scalone (gridSpan/vMerge) liczone raz.
XLSX: wszystkie arkusze, wiersz -> komórki niepuste " | ", scalone komórki tylko w komórce-kotwicy.
"""
import dataclasses
import datetime as dt
import html
import io
import re
import zipfile

from hackcore.document import Document, register
from hackcore.ingest.tools import normalize_text, soffice_convert

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
W14 = "{http://schemas.microsoft.com/office/word/2010/wordml}"

BOX_EMPTY, BOX_CHECKED = "☐", "☒"
# znaki Wingdings / Wingdings 2 używane jako kratki w formularzach (w:sym)
_SYM_EMPTY = {"F0A8", "F06F", "F071", "F0A3", "00A8", "006F", "00A3"}
_SYM_CHECKED = {"F0FE", "F078", "F0FD", "F053", "F054", "F052", "00FE", "0078", "00FD"}

CELL_SEP = " | "


# ---------------------------------------------------------------- DOCX

def _on(el, attr: str = "val") -> bool:
    """w:checked / w:default: brak atrybutu val = True."""
    v = el.get(f"{W}{attr}")
    return v is None or v.lower() not in ("0", "false", "off")


def _inline_text(el, out: list[str]) -> None:
    """Tekst elementu w kolejności dokumentu (runy, tabulatory, kratki, pola tekstowe)."""
    for ch in el:
        tag = ch.tag
        if not isinstance(tag, str) or tag in (f"{MC}Fallback", f"{W}delText", f"{W}instrText",
                                                 f"{W}rPr", f"{W}pPr"):
            continue
        if tag == f"{W}t":
            out.append(ch.text or "")
        elif tag == f"{W}tab":
            out.append("\t")
        elif tag in (f"{W}br", f"{W}cr"):
            out.append("\n")
        elif tag == f"{W}sym":
            code = (ch.get(f"{W}char") or "").upper()
            if "WINGDINGS" in (ch.get(f"{W}font") or "").upper():
                if code in _SYM_EMPTY:
                    out.append(BOX_EMPTY)
                elif code in _SYM_CHECKED:
                    out.append(BOX_CHECKED)
        elif tag == f"{W}checkBox":  # stare pole formularza (ffData) — nie ma glifu w tekście
            checked = ch.find(f"{W}checked")
            if checked is None:
                checked = ch.find(f"{W}default")
            out.append(BOX_CHECKED if checked is not None and _on(checked) else BOX_EMPTY)
            out.append(" ")
        elif tag == f"{W}p":  # akapit zagnieżdżony (np. w polu tekstowym)
            if out and not out[-1].endswith("\n"):
                out.append("\n")
            _inline_text(ch, out)
            out.append("\n")
        elif tag == f"{W}tbl":  # tabela w polu tekstowym
            out.append("\n" + "\n".join(_row_line(r) for r in _table_rows(ch)) + "\n")
        else:
            _inline_text(ch, out)


def _para_text(p) -> str:
    out: list[str] = []
    _inline_text(p, out)
    return normalize_text("".join(out).replace("\t", " "))


def _iter_children(parent, tag: str):
    """Bezpośrednie dzieci `tag` (w:tr / w:tc), także owinięte w kontrolki treści w:sdt / w:customXml."""
    for ch in parent:
        if ch.tag == tag:
            yield ch
        elif ch.tag == f"{W}sdt":
            content = ch.find(f"{W}sdtContent")
            if content is not None:
                yield from _iter_children(content, tag)
        elif ch.tag == f"{W}customXml":
            yield from _iter_children(ch, tag)


def _cell_text(tc, nested: list[list[list[str]]] | None) -> str:
    parts = []
    for el in _block_items(tc):
        if el.tag == f"{W}p":
            parts.append(_para_text(el))
        else:  # zagnieżdżona tabela
            rows = _table_rows(el, nested)
            if nested is not None:
                nested.append(rows)
            parts.extend(_row_line(r) for r in rows)
    return "\n".join(x for x in parts if x).strip()


def _table_rows(tbl, nested: list[list[list[str]]] | None = None) -> list[list[str]]:
    rows = []
    for tr in _iter_children(tbl, f"{W}tr"):
        row = []
        for tc in _iter_children(tr, f"{W}tc"):
            tcpr = tc.find(f"{W}tcPr")
            vm = tcpr.find(f"{W}vMerge") if tcpr is not None else None
            if vm is not None and vm.get(f"{W}val") != "restart":
                row.append("")  # kontynuacja scalenia pionowego — tekst jest w komórce wyżej
                continue
            row.append(_cell_text(tc, nested))
        if any(row):
            rows.append(row)
    return rows


def _row_line(row: list[str]) -> str:
    return CELL_SEP.join(c.replace("\n", " ") for c in row if c)


def _block_items(parent):
    """Akapity i tabele w kolejności (także wewnątrz blokowych kontrolek treści w:sdt)."""
    for ch in parent:
        if ch.tag in (f"{W}p", f"{W}tbl"):
            yield ch
        elif ch.tag == f"{W}sdt":
            content = ch.find(f"{W}sdtContent")
            if content is not None:
                yield from _block_items(content)
        elif ch.tag == f"{W}customXml":
            yield from _block_items(ch)


@register("docx")
def load_docx(data: bytes, max_pages: int | None = None) -> Document:
    import docx  # python-docx (MIT)

    d = docx.Document(io.BytesIO(data))
    lines: list[str] = []
    tables: list[list[list[str]]] = []
    for el in _block_items(d.element.body):
        if el.tag == f"{W}p":
            if t := _para_text(el):
                lines.append(t)
        else:
            nested: list[list[list[str]]] = []
            rows = _table_rows(el, nested)
            if rows:
                tables.append(rows)
                tables.extend(nested)
                lines.extend(line for r in rows if (line := _row_line(r)))
    return Document.from_pages(["\n".join(lines)], "docx", tables=tables)


# ---------------------------------------------------------------- XLSX

def _cell_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TAK" if v else "NIE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, dt.datetime):
        return v.date().isoformat() if v.time() == dt.time() else v.isoformat(sep=" ")
    if isinstance(v, (dt.date, dt.time)):
        return v.isoformat()
    return normalize_text(str(v))


@register("xlsx")
def load_xlsx(data: bytes, max_pages: int | None = None) -> Document:
    import openpyxl  # MIT

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)  # data_only: wartości, nie formuły
    pages: list[str] = []
    tables: list[list[list[str]]] = []
    try:
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            # openpyxl: komórki scalone poza kotwicą mają value=None -> bez dublowania
            rows = [[_cell_str(v) for v in r] for r in ws.iter_rows(values_only=True)]
            rows = [r for r in rows if any(r)]
            if not rows:
                continue
            width = max(len(r) for r in rows)
            keep = [c for c in range(width) if any(c < len(r) and r[c] for r in rows)]
            rows = [[r[c] if c < len(r) else "" for c in keep] for r in rows]
            tables.append(rows)
            body = "\n".join(_row_line(r) for r in rows)
            pages.append(f"[Arkusz: {ws.title}]\n{body}" if len(wb.worksheets) > 1 else body)
    finally:
        wb.close()
    if extra := _xlsx_shapes_and_comments(data):
        pages.append(extra)
    return Document.from_pages(pages or [""], "xlsx", tables=tables)


_XML_RUN = re.compile(r"<(?:a:)?t(?:\s[^>]*)?>([^<]*)</(?:a:)?t>")


def _xlsx_shapes_and_comments(data: bytes) -> str:
    """D-01: pola tekstowe/kształty (xl/drawings) i komentarze komórek - openpyxl ich nie czyta, a wzory urzędowe
    trzymają tam np. listę załączników. Tekst wyciągamy regexem (bez parsera XML: plik z zewnątrz)."""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(n for n in z.namelist() if re.fullmatch(r"xl/(drawings/drawing|comments)\d*\.xml", n)):
            xml = z.read(name).decode("utf-8", "replace")
            block = r"<xdr:sp\b.*?</xdr:sp>" if "drawings" in name else r"<comment\b.*?</comment>"
            for part in re.findall(block, xml, re.S):
                text = normalize_text(html.unescape("".join(_XML_RUN.findall(part))))
                if text:
                    out.append(text)
    return "[Pola tekstowe i komentarze]\n" + "\n".join(out) if out else ""


# ---------------------------------------------------------------- DOC / ODS (LibreOffice)

@register("doc")
def load_doc(data: bytes, max_pages: int | None = None) -> Document:
    return dataclasses.replace(load_docx(soffice_convert(data, "doc", "docx")), source_format="doc")


@register("ods")
def load_ods(data: bytes, max_pages: int | None = None) -> Document:
    return dataclasses.replace(load_xlsx(soffice_convert(data, "ods", "xlsx")), source_format="ods")
