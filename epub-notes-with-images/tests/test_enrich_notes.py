import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('enrich',ROOT/'scripts/enrich_notes.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
CAP='A useful diagram explains the support structure clearly.'
PNG=bytes.fromhex('89504e470d0a1a0a')

class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.epub=self.root/'book.epub';self.notes=self.root/'notes.html'
    def tearDown(self):self.tmp.cleanup()
    def fixture(self,body,highlight):
        with zipfile.ZipFile(self.epub,'w') as z:
            z.writestr('META-INF/container.xml','<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>')
            z.writestr('OPS/book.opf','<package><metadata><title>Example</title></metadata><manifest><item id="c" href="c.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c"/></spine></package>')
            z.writestr('OPS/c.xhtml','<html><body>'+body+'</body></html>');z.writestr('OPS/img.png',PNG)
        self.notes.write_text('<div class="bookTitle">Example</div><div class="noteHeading">Highlight - Page 1</div><div class="noteText">'+highlight+'</div><div class="noteHeading">Note - Page 1</div><div class="noteText">test</div>')
    def figure(self):return '<figure><img src="img.png"/><figcaption>'+CAP+'</figcaption></figure>'
    def test_caption_roundtrip(self):
        self.fixture(self.figure(),CAP);out=self.root/'out';r=m.enrich(self.epub,self.notes,out)
        self.assertEqual(len(r['records']),2);self.assertEqual(r['records'][0]['text'],CAP)
        self.assertEqual(len(r['records'][0]['images']),1)
        p=ROOT.parent/'book-notes-from-kindle/scripts/parse_kindle.py';sp=importlib.util.spec_from_file_location('parser',p);parser=importlib.util.module_from_spec(sp);sp.loader.exec_module(parser)
        parsed=parser.extract(out/'notes.html');parser.materialize_images(parsed,out/'parsed.json')
        im=parsed['records'][0]['images'][0];self.assertEqual(Path(im['src']).read_bytes(),PNG);self.assertEqual(im['caption'],CAP)
        self.assertEqual(parsed['records'][1]['adjacent_highlight_id'],1)
    def test_ambiguous_no_auto_attachment(self):
        self.fixture(self.figure()+self.figure(),CAP);r=m.enrich(self.epub,self.notes,self.root/'out');self.assertEqual(r['records'][0]['images'],[])
        choices=self.root/'choices.json';choices.write_text('{"1":["image-2"]}')
        r=m.enrich(self.epub,self.notes,self.root/'reviewed',choices);self.assertEqual(r['records'][0]['images'][0]['id'],'image-2')
    def test_nearby_not_silently_selected(self):
        self.fixture('<p>Some unique highlighted text.</p>'+self.figure(),'Some unique highlighted text.')
        r=m.enrich(self.epub,self.notes,self.root/'out');self.assertEqual(r['records'][0]['images'],[])
        review=json.loads((self.root/'out/review.json').read_text());self.assertEqual(review['records'][0]['candidates'],['image-1'])
    def test_preserve_existing_output(self):
        self.fixture(self.figure(),CAP);out=self.root/'out';out.mkdir();(out/'sentinel').write_text('keep')
        with self.assertRaises(ValueError):m.enrich(self.epub,self.notes,out)
        self.assertEqual((out/'sentinel').read_text(),'keep')
    def test_external_and_escape_resources_rejected(self):
        for href in ('https://example.com/image.png','../../../secret.png'):
            with self.assertRaises(ValueError):m.member('OPS/c.xhtml',href)

    def test_manual_rejection_is_preserved(self):
        self.fixture(self.figure(),CAP)
        choices=self.root/'choices.json';choices.write_text('{"1": []}')
        result=m.enrich(self.epub,self.notes,self.root/'out',choices)
        self.assertEqual(result['records'][0]['image_review'],'manually-rejected')
        review=json.loads((self.root/'out/review.json').read_text())
        self.assertEqual(review['records'][0]['status'],'manually-rejected')

    def test_word_boundaries_prevent_false_match(self):
        self.fixture('<p>nowhere</p>'+self.figure()+'<p>after</p>','now here '+CAP+' after')
        result=m.enrich(self.epub,self.notes,self.root/'out')
        self.assertNotIn('epub_match',result['records'][0])
        self.assertEqual(result['records'][0]['images'],[])

    def test_inline_markup_preserves_words(self):
        self.fixture('<p>some<b>where</b> now</p>'+self.figure(),'somewhere now '+CAP)
        result=m.enrich(self.epub,self.notes,self.root/'out')
        self.assertEqual(len(result['records'][0]['images']),1)

    def test_caption_occurrence_scoped_to_match(self):
        self.fixture('<p>Unique lead.</p>'+self.figure()+'<p>End.</p><p>Distant context.</p>'+self.figure(),'Unique lead. '+CAP)
        result=m.enrich(self.epub,self.notes,self.root/'out')
        self.assertEqual([i['id'] for i in result['records'][0]['images']],['image-1'])

    def test_markdown_source_is_literal(self):
        self.fixture('<p>Example</p>','---')
        result=m.enrich(self.epub,self.notes,self.root/'out')
        self.assertEqual(result['records'][0]['text'],'---')
        self.assertIn('&#45;&#45;&#45;', (self.root/'out/notes.md').read_text())
        self.assertEqual(m.markdown_text('<b>*x*</b>'),'&#60;b&#62;&#42;x&#42;&#60;&#47;b&#62;')

    def test_oversized_xml_checked_before_open(self):
        self.fixture(self.figure(),CAP)
        with patch.object(m,'MAX_MEMBER_BYTES',10), patch.object(zipfile.ZipFile,'open',side_effect=AssertionError('decompressed')):
            with self.assertRaisesRegex(ValueError,'Oversized'):m.read_epub(self.epub)

    def test_total_budget_checked_before_open(self):
        self.fixture(self.figure(),CAP)
        with patch.object(m,'MAX_ARCHIVE_BYTES',10), patch.object(zipfile.ZipFile,'open',side_effect=AssertionError('decompressed')):
            with self.assertRaisesRegex(ValueError,'cumulative'):m.read_epub(self.epub)

    def test_oversized_image_is_not_opened(self):
        self.fixture(self.figure(),CAP)
        with zipfile.ZipFile(self.epub,'a') as z:z.writestr('OPS/large.png',b'x'*2000)
        # Point at the large image without changing normal XML members.
        with zipfile.ZipFile(self.epub,'a') as z:z.writestr('OPS/c.xhtml','<html><body><img src="large.png"/></body></html>')
        original=zipfile.ZipFile.open
        def guarded(archive,name,*a,**kw):
            self.assertNotEqual(getattr(name,'filename',name),'OPS/large.png')
            return original(archive,name,*a,**kw)
        with patch.object(m,'MAX_MEMBER_BYTES',1000),patch.object(zipfile.ZipFile,'open',guarded):
            _,_,images,warnings=m.read_epub(self.epub)
        self.assertEqual(images,[]);self.assertTrue(any('Oversized' in w for w in warnings))

if __name__=='__main__':unittest.main()
