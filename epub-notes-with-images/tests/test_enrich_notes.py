import importlib.util
import json
import tempfile
import unittest
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

if __name__=='__main__':unittest.main()
