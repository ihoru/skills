#!/usr/bin/env python3
"""Extract Kindle notebook HTML or English My Clippings.txt without rewriting text."""
import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path


class NotebookParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.active = None
        self.parts = []
        self.elements = []

    def handle_starttag(self, tag, attrs):
        if tag == 'div':
            self.depth += 1
            classes = dict(attrs).get('class', '').split()
            recognized = {'bookTitle', 'authors', 'sectionHeading', 'noteHeading', 'noteText'}
            kind = next((c for c in classes if c in recognized), None)
            if kind and self.active is None:
                self.active = (kind, self.depth)
                self.parts = []
        elif tag == 'br' and self.active:
            self.parts.append('\n')

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'div':
            if self.active and self.depth == self.active[1]:
                self.elements.append((self.active[0], ''.join(self.parts).strip()))
                self.active = None
            self.depth = max(0, self.depth - 1)


def metadata(heading):
    match = re.search(r'\b(Highlight|Note|Bookmark)\b', heading, re.I)
    result = {'kind': match.group(1).lower() if match else 'unknown', 'heading': heading}
    for key, pattern in [('page', r'\bPage\s+([\d–-]+)'),
                         ('location', r'\b(?:Location|Loc\.)\s+([\d–-]+)')]:
        m = re.search(pattern, heading, re.I)
        if m:
            result[key] = m.group(1)
    return result


def parse_html(text):
    parser = NotebookParser()
    parser.feed(text)
    book = author = section = ''
    records, warnings = [], []
    current = None
    for kind, value in parser.elements:
        if kind == 'bookTitle':
            book = value
        elif kind == 'authors':
            author = value
        elif kind == 'sectionHeading':
            section = value
        elif kind == 'noteHeading':
            current = dict(metadata(value), book=book, author=author, section=section, text='')
            records.append(current)
        elif kind == 'noteText':
            if current is None:
                warnings.append('Orphan noteText requires manual inspection: ' + value)
            else:
                current['text'] += ('\n' if current['text'] else '') + value
    return records, warnings


def parse_txt(text):
    records, warnings = [], []
    for block in re.split(r'^={10,}\s*$', text, flags=re.M):
        lines = block.strip().splitlines()
        if not lines:
            continue
        if len(lines) < 2 or not lines[1].lstrip().startswith('-'):
            warnings.append('Unrecognized clipping requires manual inspection: ' + block.strip())
            continue
        record = dict(metadata(lines[1]), book=lines[0].strip(), text='\n'.join(lines[2:]).strip())
        records.append(record)
    return records, warnings


def extract(path, book=None):
    text = Path(path).read_text(encoding='utf-8-sig')
    records, warnings = parse_html(text) if Path(path).suffix.lower() in {'.html', '.htm'} else parse_txt(text)
    titles = sorted({r['book'] for r in records})
    if book is None and len(titles) > 1:
        raise ValueError('Multiple books found; select one with --book: ' + json.dumps(titles, ensure_ascii=False))
    if book is not None:
        records = [r for r in records if r['book'].casefold() == book.casefold()]
    if not records:
        raise ValueError('No matching records. Check the title, format, and source metadata.')
    seen, candidates = {}, []
    previous = None
    for index, record in enumerate(records, 1):
        record['id'] = index
        normalized = ' '.join(record['text'].split())
        key = (record['book'], record['kind'], normalized)
        if normalized and key in seen:
            record['duplicate_of'] = seen[key]
        elif normalized:
            seen[key] = index
        if record['kind'] == 'unknown':
            warnings.append(f'Record {index}: unrecognized metadata; classify manually.')
        if record['kind'] == 'note':
            same_position = previous and any(record.get(k) and record.get(k) == previous.get(k) for k in ('page', 'location'))
            if previous and previous['kind'] == 'highlight' and previous['book'] == record['book'] and same_position:
                record['adjacent_highlight_id'] = previous['id']
            else:
                warnings.append(f'Record {index}: note association requires manual inspection.')
        if record['kind'] == 'highlight' and not normalized:
            warnings.append(f'Record {index}: empty highlight.')
        if (record['kind'] == 'highlight' and normalized and len(normalized.split()) <= 7
                and 'duplicate_of' not in record and not re.match(r'(?:https?://|www\.)', normalized, re.I)):
            candidates.append({'record_id': index, 'original': record['text']})
        previous = record
    return {'source': str(Path(path).resolve()), 'book': records[0]['book'],
            'records': records, 'vocabulary_candidates': candidates, 'warnings': warnings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--book', help='Exact exported title, case-insensitive')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Output must differ from the source file.')
    if args.output.exists():
        parser.error('Output already exists; choose a new output path.')
    try:
        result = extract(args.input, args.book)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f"Saved {len(result['records'])} records, {len(result['vocabulary_candidates'])} vocabulary candidates, "
          f"and {len(result['warnings'])} warnings to {args.output}")


if __name__ == '__main__':
    main()
