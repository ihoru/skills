"""Small synthetic fixtures: no private excerpts or account configuration."""
import tempfile
import unittest
from pathlib import Path
from parse_kindle import extract


class ParseTests(unittest.TestCase):
    def run_source(self, text, suffix, book=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ('export' + suffix)
            path.write_text(text, encoding='utf-8-sig')
            return extract(path, book)

    def test_html_bookmarks_notes_entities_and_duplicates(self):
        result = self.run_source('''<div class="bookTitle">A Book</div>
<div class="authors">An Author</div>
<div class="noteHeading">Highlight (<span>yellow</span>) - Page 3</div>
<div class="noteText">calm &amp; clear</div>
<div class="noteHeading">Note - Page 3</div><div class="noteText">quote</div>
<div class="noteHeading">Bookmark - Page 4</div>
<div class="noteHeading">Highlight - Page 5</div><div class="noteText">calm &amp; clear</div>''', '.html')
        self.assertEqual(len(result['records']), 4)
        self.assertEqual(result['records'][0]['text'], 'calm & clear')
        self.assertEqual(result['records'][1]['adjacent_highlight_id'], 1)
        self.assertEqual(result['records'][2]['text'], '')
        self.assertEqual(result['records'][3]['duplicate_of'], 1)
        self.assertEqual(len(result['vocabulary_candidates']), 1)

    def test_mixed_txt_requires_selection_and_preserves_multiline(self):
        text = '''A Book (Writer)
- Your Highlight on Location 20-21 | Added on Today

First line.
Second line.
==========
B Book (Writer)
- Your Highlight on page 9 | Added on Today

Word
=========='''
        with self.assertRaises(ValueError):
            self.run_source(text, '.txt')
        result = self.run_source(text, '.txt', 'A Book (Writer)')
        self.assertEqual(result['records'][0]['text'], 'First line.\nSecond line.')
        self.assertEqual(result['records'][0]['location'], '20-21')

    def test_unknown_metadata_and_unattached_note_are_visible(self):
        text = '''A Book
- Unrecognized metadata

Preserve me
==========
A Book
- Your Note on page 99

book
=========='''
        result = self.run_source(text, '.txt')
        self.assertEqual(result['records'][0]['kind'], 'unknown')
        self.assertEqual(len(result['warnings']), 2)
        self.assertNotIn('adjacent_highlight_id', result['records'][1])

    def test_lexical_digits_are_preserved(self):
        result = self.run_source('A Book\n- Your Highlight on page 1\n\nB2\n==========', '.txt')
        self.assertEqual(result['vocabulary_candidates'][0]['original'], 'B2')


if __name__ == '__main__':
    unittest.main()
