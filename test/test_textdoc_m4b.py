"""End-to-end: Markdown in, .m4b with real chapter titles out. Needs Kokoro (model download) and ffmpeg."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from audiblez.core import main

FIXTURES = Path(__file__).parent / 'fixtures'


class MarkdownM4bTest(unittest.TestCase):
    def test_chapter_titles_and_metadata(self):
        with tempfile.TemporaryDirectory() as out:
            main(str(FIXTURES / 'summary.md'), 'af_sky', False, 1.0, output_folder=out,
                 max_sentences=1, title='Override Title')
            m4b = Path(out) / 'summary.m4b'
            self.assertTrue(m4b.exists())
            probe = json.loads(subprocess.check_output(
                ['ffprobe', '-v', 'quiet', '-of', 'json', '-show_chapters', '-show_format', str(m4b)]))
        titles = [c['tags']['title'] for c in probe['chapters']]
        self.assertEqual(titles, ['Introduction', 'Part 1: Background', 'Part 2: Lists and code', 'Conclusion'])
        tags = probe['format']['tags']
        self.assertEqual(tags['title'], 'Override Title')  # flag beats front matter
        self.assertEqual(tags['artist'], 'Ada Lovelace')


if __name__ == '__main__':
    unittest.main()
