import re
import tempfile
import unittest
from pathlib import Path

from audiblez.core import default_chapters, find_document_chapters_and_extract_texts, load_book
from audiblez.textdoc import EQUATION_NOTE

FIXTURES = Path(__file__).parent / 'fixtures'


def chapters_of(path):
    book = load_book(path)
    return book, default_chapters(book, find_document_chapters_and_extract_texts(book))


def meta(book, name):
    values = book.get_metadata('DC', name)
    return values[0][0] if values else ''


class MarkdownTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book, cls.chapters = chapters_of(FIXTURES / 'summary.md')
        cls.text = {c.title: c.extracted_text for c in cls.chapters}
        cls.all_text = '\n'.join(cls.text.values())

    def test_chapters_split_at_h2_with_real_titles(self):
        self.assertEqual(list(self.text), ['Introduction', 'Part 1: Background', 'Part 2: Lists and code', 'Conclusion'])

    def test_front_matter_metadata_wins(self):
        self.assertEqual(meta(self.book, 'title'), 'Attention, Briefly')
        self.assertEqual(meta(self.book, 'creator'), 'Ada Lovelace')

    def test_preamble_metadata_skipped_prose_kept(self):
        intro = self.text['Introduction']
        self.assertIn('This summary is written to be read aloud.', intro)
        self.assertNotIn('arXiv', self.all_text)
        self.assertNotIn('Approximately 300 words', self.all_text)

    def test_maths_replaced_once_per_paragraph(self):
        part1 = self.text['Part 1: Background']
        attention_line = next(l for l in part1.splitlines() if l.startswith('The attention weight'))
        self.assertEqual(attention_line.count(EQUATION_NOTE), 1)
        self.assertEqual(part1.count(EQUATION_NOTE), 2)  # inline paragraph + display block
        self.assertNotIn('a_{ij}', self.all_text)
        self.assertNotIn('\\frac', self.all_text)
        self.assertIn('$5 to train on a laptop, or $10 with a GPU', part1)  # currency is not maths
        self.assertEqual(self.text['Conclusion'].count(EQUATION_NOTE), 1)  # \( x^2 \)
        self.assertIn('compares token with token, and', part1)  # no space left before punctuation

    def test_no_markup_reaches_tts(self):
        for marker in ('*', '#', '|', '](', '$$'):
            self.assertNotIn(marker, self.all_text)
        self.assertIsNone(re.search(r'\[[^\]]+\]\([^)]*\)', self.all_text))
        self.assertIn('See the project page for details.', self.all_text)
        self.assertIn('matters', self.all_text)

    def test_list_items_read_once(self):
        part2 = self.text['Part 2: Lists and code']
        self.assertIn('Three ideas matter:\n', part2)  # no '.' appended after ':'
        for item in ('tight item two', 'nested item', 'Loose item one has a paragraph.'):
            self.assertEqual(part2.count(item), 1, item)

    def test_code_tables_images_dropped(self):
        self.assertNotIn('never be read', self.all_text)
        self.assertNotIn('tablecellmarker', self.all_text)
        self.assertNotIn('a figure', self.all_text)
        self.assertIn('inline_code', self.text['Conclusion'])

    def test_byline_and_h1_used_without_front_matter(self):
        body = (FIXTURES / 'summary.md').read_text().split('---', 2)[2]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'no_front_matter.md'
            path.write_text(body)
            book, _ = chapters_of(path)
        self.assertEqual(meta(book, 'title'), 'A Short Paper Summary')
        self.assertEqual(meta(book, 'creator'), 'Grace Hopper and Alan Turing')

    def test_no_headings_is_one_chapter_read_in_full(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'plain.md'
            path.write_text('A short line without a full stop\n\nA sentence.\n')
            book, chapters = chapters_of(path)
        self.assertEqual(len(chapters), 1)
        self.assertIn('A short line without a full stop', chapters[0].extracted_text)
        self.assertEqual(meta(book, 'title'), 'plain')


def extract(markdown):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / 'case.md'
        path.write_text(markdown)
        book, chapters = chapters_of(path)
    return '\n'.join(c.extracted_text for c in chapters)


class MarkdownEdgeCaseTest(unittest.TestCase):
    def test_dollars_inside_code_spans_are_not_maths(self):
        text = extract('Run `$$not math$$` and ``one ` tick and $notmath$`` now.\n')
        self.assertIn('$$not math$$', text)
        self.assertIn('one ` tick and $notmath$', text)
        self.assertNotIn(EQUATION_NOTE, text)

    def test_footnotes_not_read(self):
        text = extract('A claim.[^1] Another.[^note]\n\n[^1]: The source.\n    More source.\n\n[^note]: Second.\n\nAfter.\n')
        self.assertNotIn('[^', text)
        self.assertNotIn('source', text)
        self.assertIn('A claim. Another.', text)
        self.assertIn('After.', text)

    def test_maths_between_escaped_backticks_is_still_maths(self):
        text = extract('Literal \\` opener, maths $escaped_math$, and literal \\` closer.\n')
        self.assertNotIn('escaped_math', text)
        self.assertIn(EQUATION_NOTE, text)

    def test_unmatched_backticks_do_not_pair_across_blocks(self):
        text = extract('# T\n\n## A\n\nUnmatched ` opener.\n\n### Heading with $boundary_math$\n\nClosing ` marker.\n')
        self.assertNotIn('boundary_math', text)

    def test_indented_content_after_footnote_survives(self):
        text = extract('A claim.[^n]\n\n[^n]: Source text.\n\n - one-space list survives\n\n   Three-space paragraph survives.\n')
        self.assertIn('one-space list survives', text)
        self.assertIn('Three-space paragraph survives.', text)
        self.assertNotIn('Source text', text)

    def test_same_line_double_dollar_maths(self):
        text = extract('Before $$double_inline_math$$ after.\n')
        self.assertNotIn('$', text)
        self.assertIn('Before after. ' + EQUATION_NOTE, text)

    def test_unblanked_line_after_footnote_continues_it(self):
        # CommonMark lazy continuation (pandoc agrees): the next line belongs to the footnote, so it isn't read
        text = extract('A claim.[^n]\n\n[^n]: Source text.\nStill the footnote.\n\nNext paragraph.\n')
        self.assertNotIn('Still the footnote', text)
        self.assertIn('Next paragraph.', text)

    def test_raw_html_container_text_kept(self):
        text = extract('Before.\n\n<div>Inside a raw div.</div>\n\nAfter.\n')
        self.assertIn('Inside a raw div.', text)

    def test_empty_inputs_have_no_chapters(self):
        for content in ('', '---\ntitle: Only front matter\n---\n', '# Just a title\n'):
            self.assertEqual(extract(content), '', repr(content))


class ExtractorTest(unittest.TestCase):
    """block_text is shared with the epub path."""

    def blocks(self, html):
        from bs4 import BeautifulSoup
        from audiblez.core import block_text
        tags = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li']
        return [t for t in (block_text(e) for e in BeautifulSoup(html, 'html.parser').find_all(tags)) if t]

    def test_wrapped_list_item_text_kept(self):
        self.assertEqual(self.blocks('<ul><li><div>wrapped item text</div></li></ul>'), ['wrapped item text'])

    def test_nested_and_loose_items_read_once(self):
        html = '<ul><li>outer<ul><li>inner</li></ul></li><li><p>loose</p></li></ul>'
        self.assertEqual(self.blocks(html), ['outer', 'inner', 'loose'])


class TxtTest(unittest.TestCase):
    def test_hash_headings_split_chapters(self):
        book, chapters = chapters_of(FIXTURES / 'notes.txt')
        self.assertEqual([c.title for c in chapters], ['Introduction', 'First heading', 'Second heading'])
        self.assertIn('introduction that wraps across two lines.', chapters[0].extracted_text)
        self.assertIn('a price of $5 stays.', chapters[1].extracted_text)
        self.assertEqual(meta(book, 'title'), 'notes')


class LoadBookTest(unittest.TestCase):
    def test_unsupported_suffix(self):
        with self.assertRaises(ValueError):
            load_book('book.pdf')


if __name__ == '__main__':
    unittest.main()
