# -*- coding: utf-8 -*-
"""Load Markdown (.md) and plain-text (.txt) files as an in-memory EpubBook, one EpubHtml per section,
so the epub pipeline (chapter table, text extraction, m4b metadata) handles them unchanged."""
import html
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString
from ebooklib import epub
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.texmath import texmath_plugin

EQUATION_NOTE = 'See the document for equations.'
SENTENCE_END = re.compile(r'[.!?…]["”’\')\]]*$')
HEADINGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
READ_BLOCKS = {'p', 'ul', 'ol', 'blockquote', 'hr'}  # top-level blocks the extractor reads as they are
TEXT_BLOCKS = ['p', 'li', 'blockquote', 'td', 'th'] + sorted(HEADINGS)
BYLINE_CUT = re.compile(r'\s+[—–|]\s+|,\s*arXiv', re.I)


def math_parser(preset):
    """The parser, not regexes, decides what is code, maths or a footnote. $…$ follows pandoc's rule
    (no space inside the dollars, closing $ not followed by a digit), so '$5 or $10' is not maths."""
    return (MarkdownIt(preset)
            .use(dollarmath_plugin, allow_space=False, allow_digits=False, double_inline=True)
            .use(texmath_plugin, delimiters='brackets')  # \( … \) and \[ … \]
            .use(footnote_plugin))


MARKDOWN = math_parser('commonmark').enable('table')
PLAIN = math_parser('zero')  # .txt: paragraphs and maths only, no other markup


def split_front_matter(text):
    """Return ({'title':…, 'author':…}, body) for a leading --- key: value --- block."""
    m = re.match(r'---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)', text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(':')
        if sep and key.strip() in ('title', 'author') and value.strip():
            meta[key.strip()] = value.strip().strip('"\'')
    return meta, text[m.end():]


def txt_to_html(text):
    """Plain text: blank lines separate paragraphs, '# Heading' lines are headings; nothing else is markup."""
    parts = []
    for block in re.split(r'\n[ \t]*\n', text):
        para = []
        for line in block.splitlines():
            if m := re.match(r'(#{1,6})\s+(.*\S)', line):
                if para:
                    parts.append(f'<p>{PLAIN.renderInline(" ".join(para))}</p>')
                    para = []
                level = len(m.group(1))
                parts.append(f'<h{level}>{html.escape(m.group(2))}</h{level}>')
            elif line.strip():
                para.append(line.strip())
        if para:
            parts.append(f'<p>{PLAIN.renderInline(" ".join(para))}</p>')
    return '\n'.join(parts)


def drop_unreadable(soup):
    """Remove what isn't read aloud: code blocks, tables, images, footnotes; replace maths with EQUATION_NOTE."""
    for kind, selector in (('code block', 'pre'), ('table', 'table'), ('image', 'img'),
                           ('footnote', 'sup.footnote-ref, hr.footnotes-sep, section.footnotes')):
        dropped = soup.select(selector)
        for tag in dropped:
            tag.decompose()
        if dropped and kind != 'footnote':
            print(f'Not reading {len(dropped)} {kind}(s) aloud.')

    # display maths: dollarmath renders <div class="math block">, texmath <section><eqn>
    for block in soup.select('div.math.block, eqn'):
        target = block.parent if block.parent and block.parent.name == 'section' else block
        note = soup.new_tag('p')
        note.string = EQUATION_NOTE
        target.replace_with(note)

    # inline maths: <span class="math inline">, <div class="math inline"> (same-line $$…$$) or <eq>; its text
    # block gets one EQUATION_NOTE
    touched = []
    for eq in soup.select('span.math, div.math.inline, eq'):
        container = eq.find_parent(TEXT_BLOCKS)
        eq.decompose()
        if container is not None and container not in touched:
            touched.append(container)
    for container in touched:
        if container.find(['p', 'ul', 'ol', 'li', 'blockquote']):  # has nested blocks: keep structure
            container.append(' ' + EQUATION_NOTE)
            continue
        text = re.sub(r'[ \t]+([,.;:!?])', r'\1', re.sub(r'\s+', ' ', container.get_text()))
        container.string = text.strip() + ' ' + EQUATION_NOTE


def byline_authors(text):
    """Guess authors from a byline such as 'Ann Smith and Bo Li — arXiv:2601.22170v2, August 2026'."""
    candidate = BYLINE_CUT.split(text, maxsplit=1)[0].strip()
    words = candidate.split()
    if 0 < len(words) <= 12 and not re.search(r'\d', candidate) and any(w[:1].isupper() for w in words):
        return candidate
    return ''


def load_text_book(file_path):
    """Build an EpubBook from a .md or .txt file. Metadata priority: front matter > byline > first H1 / file stem."""
    path = Path(file_path)
    meta, body = split_front_matter(path.read_text(encoding='utf-8'))
    rendered = MARKDOWN.render(body) if path.suffix.lower() == '.md' else txt_to_html(body)
    soup = BeautifulSoup(rendered, 'html.parser')
    drop_unreadable(soup)

    top = [n for n in soup.children if not (isinstance(n, NavigableString) and not n.strip())]
    for i, node in enumerate(top):  # raw HTML (<div>, <details>, bare text) would be skipped by the extractor
        if (node.name not in READ_BLOCKS | HEADINGS) and node.get_text(strip=True):
            para = soup.new_tag('p')
            para.string = node.get_text(' ', strip=True)
            node.replace_with(para)
            top[i] = para
    h1s = [n for n in top if n.name == 'h1']
    title_h1 = h1s[0] if len(h1s) == 1 else None  # a lone H1 is the document title, not a chapter
    doc_title = title_h1.get_text(' ', strip=True) if title_h1 else ''
    levels = sorted({int(n.name[1]) for n in top if n.name in HEADINGS and n is not title_h1})
    split_tag = f'h{levels[0]}' if levels else None  # chapters at the shallowest remaining heading level

    # sections: (title, [nodes]); the first one (title None) is the preamble before any split heading
    sections = [(None, [])]
    for node in top:
        if node.name == split_tag:
            sections.append((node.get_text(' ', strip=True), [node]))
        elif node is not title_h1:
            sections[-1][1].append(node)

    # preamble: paragraphs that aren't sentences are metadata (byline, word counts...), never read aloud
    # (only when there are sections: without headings the whole file is one chapter, read in full)
    preamble_kept, byline = [], ''
    for node in sections[0][1]:
        text = node.get_text(' ', strip=True)
        if len(sections) > 1 and node.name == 'p' and not SENTENCE_END.search(text):
            print(f'Skipping preamble line (metadata, not prose): {text}')
            byline = byline or byline_authors(text)
        else:
            preamble_kept.append(node)
    book_title = meta.get('title') or doc_title or path.stem
    sections[0] = ('Introduction' if len(sections) > 1 else book_title, preamble_kept)

    book = epub.EpubBook()
    book.set_title(book_title)
    if author := meta.get('author') or byline:
        book.add_author(author)
    book.audiblez_text_source = True  # core.main selects every non-empty section instead of guessing by file name
    for i, (title, nodes) in enumerate(s for s in sections if any(n.get_text(strip=True) for n in s[1])):
        content = ''.join(str(n) for n in nodes)
        book.add_item(epub.EpubHtml(title=title or f'Part {i + 1}', file_name=f'chapter_{i:02d}.xhtml',
                                    content=f'<html><body>{content}</body></html>'))
    return book
