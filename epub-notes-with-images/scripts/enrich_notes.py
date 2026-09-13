#!/usr/bin/env python3
"""Enrich Kindle HTML with EPUB illustrations; Python standard library only."""
import argparse
import base64
import hashlib
import html
import importlib.util
import json
import posixpath
import re
import unicodedata
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET


def normalize(text):
    return ''.join(c.lower() for c in unicodedata.normalize('NFKC', text) if c.isalnum())


def member(base, href):
    url = urlsplit(href)
    if url.scheme or url.netloc:
        raise ValueError('External EPUB resource is unsupported: ' + href)
    name = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(url.path)))
    if name.startswith('../') or name.startswith('/'):
        raise ValueError('EPUB resource escapes archive: ' + href)
    return name


def tag(element):
    return element.tag.rsplit('}', 1)[-1]


def read_epub(path):
    docs, images, warnings = [], [], []
    with zipfile.ZipFile(path) as archive:
        def xml(name):
            data = archive.read(name)
            if len(data) > 20_000_000 or b'<!ENTITY' in data.upper():
                raise ValueError('Oversized or entity-containing EPUB XML: ' + name)
            return ET.fromstring(data)
        container = xml('META-INF/container.xml')
        opf = next(e.attrib['full-path'] for e in container.iter() if tag(e) == 'rootfile')
        package = xml(opf)
        manifest = {e.attrib['id']: e.attrib for e in package.iter() if tag(e) == 'item'}
        title = next((''.join(e.itertext()) for e in package.iter() if tag(e) == 'title'), '')
        for item in (e for e in package.iter() if tag(e) == 'itemref'):
            resource = manifest[item.attrib['idref']]
            if resource.get('media-type') != 'application/xhtml+xml':
                continue
            name = member(opf, resource['href']); root = xml(name)
            body = next((e for e in root.iter() if tag(e) == 'body'), root)
            offsets, text = {}, []
            def walk(e):
                start = len(text)
                text.extend(normalize(e.text or ''))
                for child in e:
                    walk(child); text.extend(normalize(child.tail or ''))
                offsets[id(e)] = (start, len(text))
            walk(body); hay = ''.join(text)
            parents = {id(c): p for p in body.iter() for c in p}
            doc = {'href': name, 'text': hay, 'images': []}
            for e in body.iter():
                if tag(e) not in ('img', 'image'):
                    continue
                src = e.get('src') or e.get('{http://www.w3.org/1999/xlink}href') or e.get('href')
                if not src: continue
                image_id = 'image-' + str(len(images) + 1)
                caption = ''; ancestor = parents.get(id(e))
                while ancestor is not None:
                    if tag(ancestor) == 'figure':
                        caption = ' '.join(''.join(c.itertext()).strip() for c in ancestor.iter() if tag(c) == 'figcaption')
                        break
                    ancestor = parents.get(id(ancestor))
                try:
                    image_path = member(name, src); data = archive.read(image_path)
                    ext = Path(image_path).suffix.lower()
                    mime = {'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.gif':'image/gif','.webp':'image/webp'}.get(ext)
                    if not mime or len(data) > 20_000_000:
                        raise ValueError('Unsupported or oversized image; render/review manually')
                except (ValueError, KeyError) as err:
                    warnings.append(f'{name}: {src}: {err}'); continue
                record = {'id':image_id,'epub_href':name,'epub_image':image_path,'caption':caption,'alt':e.get('alt',''), 'offset':offsets[id(e)][0], 'src':'data:'+mime+';base64,'+base64.b64encode(data).decode(), 'asset_name':hashlib.sha256(data).hexdigest()[:16]+ext}
                images.append(record); doc['images'].append(record)
            docs.append(doc)
    return title, docs, images, warnings


def enrich(epub, notebook, output, select=None):
    parser_path = Path(__file__).resolve().parents[2] / 'book-notes-from-kindle/scripts/parse_kindle.py'
    if not parser_path.exists():
        raise ValueError('Install sibling book-notes-from-kindle alongside this skill.')
    spec = importlib.util.spec_from_file_location('kindle_parser', parser_path)
    parser = importlib.util.module_from_spec(spec); spec.loader.exec_module(parser)
    source = parser.extract(notebook)
    title, docs, images, warnings = read_epub(epub)
    choices = json.loads(Path(select).read_text()) if select else {}
    if not isinstance(choices, dict) or any(not isinstance(v, list) or any(not isinstance(i, str) for i in v) for v in choices.values()):
        raise ValueError('Selections must map record IDs to lists of image IDs.')
    by_id = {im['id']: im for im in images}
    review = []
    for record in source['records']:
        needle = normalize(record['text']); hits = []
        if record['kind'] == 'highlight' and needle:
            for doc in docs:
                hits.extend((doc, m.start(), m.end()) for m in re.finditer(re.escape(needle), doc['text']))
        selected = []; candidates = []
        if len(hits) == 1:
            doc, start, end = hits[0]
            record['epub_match'] = {'href':doc['href'], 'normalized_start':start,'normalized_end':end}
            for im in doc['images']:
                caption = normalize(im['caption'])
                reason = 'caption-contained' if len(caption) >= 30 and caption in needle else ('inside-highlight-span' if start < im['offset'] < end else None)
                if reason: selected.append(dict(im, association=reason))
                elif abs(im['offset']-start) < 1500 or abs(im['offset']-end) < 1500:
                    candidates.append(im['id'])
        if str(record['id']) in choices:
            selected = [dict(by_id[i], association='manually-reviewed') for i in choices[str(record['id'])]]
        record['images'] = selected
        review.append({'record_id':record['id'],'text':record['text'],'match_count':len(hits),'selected':[im['id'] for im in selected],'candidates':candidates,'status':'attached' if selected else 'review' if candidates or len(hits)!=1 else 'no-associated-image'})
    unknown = set(choices)-{str(r['id']) for r in source['records']}
    if unknown: raise ValueError('Unknown selected record IDs: '+str(unknown))
    if output.exists(): raise ValueError('Output directory already exists; choose a new directory.')
    output.mkdir(parents=True); (output/'assets').mkdir()
    source.update(schema='epub-notes/v1', epub_title=title, epub_source=str(Path(epub).resolve()), warnings=source['warnings']+warnings)
    # Keep the original records and metadata; captions are image metadata, never new highlights.
    (output/'notes.json').write_text(json.dumps(source,ensure_ascii=False,indent=2))
    (output/'review.json').write_text(json.dumps({'records':review,'images':[{k:v for k,v in im.items() if k!='src'} for im in images], 'warnings':warnings},ensure_ascii=False,indent=2))
    for im in images:
        (output/'assets'/im['asset_name']).write_bytes(base64.b64decode(im['src'].split(',',1)[1]))
    css='body{max-width:800px;margin:40px auto;padding:0 24px;font:18px/1.6 Georgia,serif}article{border-top:1px solid #ccc;padding:20px 0}img{max-width:100%;height:auto}figure{margin:20px 0}figcaption,small{color:#555}'
    parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Illustrated notes</title><style>'+css+'</style><body><h1>'+html.escape(source['book'])+'</h1><p>Images recovered from the supplied EPUB. This file includes only records present in the supplied notebook; it does not establish cloud completeness.</p>']
    md=['# '+source['book'],'','Images recovered from the supplied EPUB; only supplied notebook records are included.','']
    for r in source['records']:
        heading=r.get('heading',r['kind']);parts.append('<article><h2>'+html.escape(heading)+'</h2><p>'+html.escape(r['text']).replace('\n','<br>')+'</p>');md.extend(['## '+heading,'',r['text'],''])
        for im in r['images']:
            parts.append('<figure><img src="'+im['src']+'" alt="'+html.escape(im['alt'],quote=True)+'"><figcaption>'+html.escape(im['caption'])+'</figcaption></figure>')
            md.extend(['!['+im['alt'].replace(']','\\]')+'](assets/'+im['asset_name']+')','',im['caption'],''])
        parts.append('</article>')
    manifest=json.dumps(source,ensure_ascii=False).replace('<','\\u003c')
    parts.append('<script type="application/json" id="epub-notes-manifest">'+manifest+'</script></body></html>')
    (output/'notes.html').write_text('\n'.join(parts));(output/'notes.md').write_text('\n'.join(md))
    return source


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('epub',type=Path);p.add_argument('notebook',type=Path);p.add_argument('--output-dir',required=True,type=Path);p.add_argument('--select',type=Path,help='JSON object mapping record IDs to image ID lists, e.g. {"1":["image-2"]}');a=p.parse_args()
    try: result=enrich(a.epub,a.notebook,a.output_dir,a.select)
    except (ValueError,OSError,KeyError,ET.ParseError,zipfile.BadZipFile) as e:p.error(str(e))
    print(f"Saved {len(result['records'])} records with {sum(len(r['images']) for r in result['records'])} image associations to {a.output_dir}")
if __name__=='__main__':main()
