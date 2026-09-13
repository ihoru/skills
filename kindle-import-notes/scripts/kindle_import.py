#!/usr/bin/env python3
"""Offline-first Kindle annotation import. No device writes without install --apply."""
import argparse
import base64
import hashlib
import json
import re
import sqlite3
import struct
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

SKILL = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((SKILL / 'references/schema-5.19.6.json').read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def output_dir(path):
    p = Path(path).resolve()
    require(SKILL.parent not in p.parents and p != SKILL.parent,
            'Keep book data and backups outside the skills repository')
    p.mkdir(parents=True, exist_ok=False)
    p.chmod(0o700)
    return p


def db(path):
    c = sqlite3.connect('file:' + quote(str(Path(path).resolve()), safe='/') + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


def validate_schema(c):
    actual = {r[0]: [v[1] for v in c.execute('pragma table_info("' + r[0].replace('"', '""') + '")')]
              for r in c.execute("select name from sqlite_master where type='table'")}
    require(actual == SCHEMA, 'Unrecognized schema; inspect it and obtain native offline samples before adapting code')
    require(c.execute('pragma integrity_check').fetchone()[0] == 'ok', 'SQLite integrity check failed')


def check_quiescent(path):
    for suffix in ('-wal', '-shm', '-journal'):
        require(not Path(str(path) + suffix).exists(), 'SQLite journal present; obtain a quiescent snapshot')


def discover(storage=None):
    roots = [Path(storage)] if storage else list(Path('/run/user').glob('*/gvfs/mtp:host=*/Internal Storage'))
    results = []
    for root in roots:
        for p in (root / 'system/ksdk/.annotations').glob('*/ksdk_annotation_v1.db'):
            results.append((root, p))
    require(len(results) == 1, 'Select exactly one connected Kindle/account; use --storage, resolve multiple profiles manually')
    return results[0]


def inspect(args):
    root, path = discover(args.storage)
    version = (root / 'system/version.txt').read_text().strip()
    check_quiescent(path)
    before = digest(path)
    out = output_dir(args.output)
    (out / 'backup.sqlite').write_bytes(path.read_bytes())
    check_quiescent(path)
    require(before == digest(path) == digest(out / 'backup.sqlite'), 'Database changed while backing up; reconnect and retry')
    with db(out / 'backup.sqlite') as c:
        validate_schema(c)
        books = [r[0] for r in c.execute('select book_id from book_state')]
    # Return names for selection, never assume titles uniquely identify editions.
    files = [str(p) for p in (root / 'documents').rglob('*.kfx')]
    write(out / 'snapshot.json', {'firmware': version, 'storage': str(root), 'database': str(path),
                                 'backup_sha256': before, 'books': books, 'kfx_files': files})
    print('Snapshot:', out / 'snapshot.json')


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text).casefold()
                   if c.isalnum() or unicodedata.combining(c))


def normalized_run(text, positions):
    """Normalize a complete run, retaining provenance through decomposition/reordering."""
    units, combining = [], []
    def flush():
        units.extend(sorted(combining, key=lambda x: unicodedata.combining(x[0])))
        combining.clear()
    for char, pid in zip(text, positions):
        for decomposed in unicodedata.normalize('NFKD', char):
            if unicodedata.combining(decomposed):
                combining.append((decomposed, pid))
            else:
                flush()
                units.append((decomposed, pid))
    flush()
    filtered = [(folded, pid) for char, pid in units for folded in char.casefold()
                if folded.isalnum() or unicodedata.combining(folded)]
    normalized = normalize(text)
    require(normalized == ''.join(ch for ch, _ in filtered), 'Unicode provenance mismatch')
    return normalized, [pid for _, pid in filtered]


def snapshot_fingerprint(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_mapping_snapshot(mapping, snapshot):
    require(mapping.get('snapshot_fingerprint') == snapshot_fingerprint(snapshot),
            'Mapping belongs to a different snapshot; remap against the selected snapshot')
    require(mapping['book_id'] in snapshot['books'], 'Mapping book is not listed by snapshot')
    require(mapping['kfx_path'] in snapshot['kfx_files'], 'Mapping KFX is not listed by snapshot')
    require(digest(mapping['kfx_path']) == mapping['kfx_sha256'], 'Mapping KFX changed; remap')


def position(pid, eid, offset):
    return {'shortPosition': pid, 'longPosition': base64.b64encode(struct.pack('<BII', 1, int(eid), offset)).decode()}


def map_records(records, chunks, choices=None):
    choices = choices or {}
    hay, refs, chars = [], [], {}
    for chunk in sorted(chunks, key=lambda x: x['pid']):
        for i, char in enumerate(chunk.get('text') or ''):
            pid = chunk['pid'] + i
            require(pid not in chars, 'Overlapping KFX text positions')
            chars[pid] = (char, chunk['eid'], chunk['eid_offset'] + i)
    run = []
    def flush_run():
        if run:
            normalized, provenance = normalized_run(''.join(chars[p][0] for p in run), run)
            hay.append(normalized)
            refs.extend(provenance)
            # An unsearchable delimiter prevents matches across images or missing PIDs.
            hay.append('\x00')
            refs.append(None)
            run.clear()
    for pid in sorted(chars):
        if run and pid != run[-1] + 1:
            flush_run()
        run.append(pid)
    flush_run()
    hay = ''.join(hay)
    result, resolved = [], {}
    require(len({str(r['id']) for r in records}) == len(records), 'Duplicate input record IDs')
    for r in records:
        item = dict(r)
        ident = str(r['id'])
        choice = choices.get(ident, {})
        require(r['kind'] in ('highlight', 'note'), 'Only highlights and text notes are supported')
        anchor = choice.get('anchor_text') or r.get('anchor_text')
        attach = choice.get('attach_to', r.get('attach_to'))
        if r['kind'] == 'highlight':
            anchor = r['text']
        if r['kind'] == 'note' and attach is not None:
            parent = resolved.get(str(attach))
            if parent:
                item.update(start_position=parent['end_position'], end_position=parent['end_position'], status='mapped')
            else:
                item.update(status='unresolved', reason='Attached highlight must precede the note and be resolved')
        elif not anchor or not normalize(anchor):
            item.update(status='unresolved', reason='Note requires reviewed attach_to or anchor_text; adjacency alone is insufficient')
        else:
            needle = normalize(anchor)
            found = [m.start() for m in re.finditer('(?=' + re.escape(needle) + ')', hay)]
            spans = [(min(refs[m:m+len(needle)]), max(refs[m:m+len(needle)])) for m in found]
            item['candidates'] = [{'start': a, 'end': z, 'context': ''.join(chars.get(i, (' ',))[0]
                                   for i in range(max(0, a - 100), z + 101))} for a, z in spans]
            pick = choice.get('candidate')
            if pick is None and len(spans) == 1:
                pick = 1
            if pick is None:
                item.update(status='unresolved', reason='No match' if not spans else 'Choose a 1-based candidate using page/context')
            else:
                require(isinstance(pick, int) and 1 <= pick <= len(spans), 'Invalid candidate choice for ' + ident)
                a, z = spans[pick - 1]
                leading = re.match(r'^\W*', anchor).group()
                trailing = re.search(r'\W*$', anchor).group()
                if leading and ''.join(chars.get(i, ('',))[0] for i in range(a-len(leading), a)) == leading:
                    a -= len(leading)
                if trailing and ''.join(chars.get(i, ('',))[0] for i in range(z+1, z+1+len(trailing))) == trailing:
                    z += len(trailing)
                require(all(i in chars for i in range(a, z+1)), 'Discontinuous KFX positions')
                extracted = ''.join(chars[i][0] for i in range(a, z+1))
                require(normalize(extracted) == needle, 'Non-contiguous or reordered matching span; review manually')
                def at(p):
                    return position(p, chars[p][1], chars[p][2])
                item.update(start_position=at(a), end_position=at(z), matched_text=extracted, status='mapped')
        if item['status'] == 'mapped':
            resolved[ident] = item
        result.append(item)
    return result


def load_notes(path, parser):
    if Path(path).suffix.lower() == '.json':
        data = read(path)
    else:
        require(Path(parser).is_file(), 'Sibling Kindle parser missing; supply --parser')
        # Parser writes only in the fresh work directory, not next to user input.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'parsed.json'
            subprocess.run([sys.executable, str(parser), str(path), '--output', str(dest)], check=True, capture_output=True)
            data = read(dest)
    records = data if isinstance(data, list) else data['records']
    for i, r in enumerate(records, 1):
        r.setdefault('id', i)
    return records


def mapping(args):
    out = output_dir(args.output)
    snapshot = read(Path(args.snapshot) / 'snapshot.json')
    require(args.book_id in snapshot['books'], 'Book ID missing from snapshot')
    kfx = Path(args.kfx)
    require(str(kfx) in snapshot['kfx_files'], 'Choose a downloaded KFX listed by inspect')
    asin = args.book_id.split('-PDOC-')[0]
    require('-PDOC-' in args.book_id and asin in kfx.name, 'This adapter requires a matching Send-to-Kindle PDOC')
    sys.path.insert(0, str(Path(args.kfxlib).resolve()))
    from kfxlib.yj_book import YJ_Book
    data = kfx.read_bytes()
    (out / 'book.kfx').write_bytes(data)
    book = YJ_Book(str(out / 'book.kfx'))
    book.decode_book(set_approximate_pages=0)
    chunks = [vars(x) for x in book.collect_content_position_info()]
    records = load_notes(args.notes, args.parser)
    mapped = map_records(records, chunks, read(args.choices) if args.choices else None)
    write(out / 'mapping.json', {'snapshot_fingerprint': snapshot_fingerprint(snapshot),
                               'book_id': args.book_id, 'kfx_sha256': hashlib.sha256(data).hexdigest(),
                               'kfx_path': str(kfx), 'records': mapped})
    write(out / 'chunks.json', chunks)
    print('Mapped:', sum(r['status'] == 'mapped' for r in mapped), 'of', len(mapped), '; review mapping.json')


def semantic(payload):
    meta = payload.get('json_metadata', '{}')
    try:
        meta = json.loads(meta)
    except json.JSONDecodeError:
        # A synced note may contain an extra JSON escaping layer.
        meta = json.loads(meta.replace('\\"', '"'))
    return (payload['type'], payload['book_data'], payload['start_position']['shortPosition'],
            payload['end_position']['shortPosition'],
            payload['start_position'].get('longPosition', ''), payload['end_position'].get('longPosition', ''), meta.get('note_text') if isinstance(meta, dict) else None)


def prepare_database(source, target, mapping_data, firmware, previous=None):
    require(re.match(r'^Kindle 5\.19\.6(?:\s|$)', firmware), 'Unsupported firmware; inspect native schema/queue before adapting')
    if previous:
        require(previous.get('status') == 'installed', 'Previous receipt must confirm installation')
    require(mapping_data['records'] and all(r['status'] == 'mapped' for r in mapping_data['records']), 'Resolve every record before preparation')
    with db(source) as orig:
        validate_schema(orig)
        c = sqlite3.connect(target)
        c.row_factory = sqlite3.Row
        orig.backup(c)
        book_id = mapping_data['book_id']
        require(orig.execute('select 1 from book_state where book_id=?', (book_id,)).fetchone(), 'Unknown target book')
        m = re.fullmatch(r'(.+)-PDOC-(CR!.+)-([01])', book_id)
        require(m, 'Unsupported book identity')
        book_data = dict(asin=m[1], contentType='PDOC', guid=m[2], isOwnedByCustomer=int(m[3]), isSample=0)
        now = int(time.time()*1000)
        added, queued, ids = 0, 0, []
        try:
            for r in mapping_data['records']:
                for field in ('created_time', 'modified_time'):
                    require(field not in r or (isinstance(r[field], int) and r[field] >= 0), 'Timestamp must be Unix milliseconds')
                kind = r['kind']
                require(kind in ('highlight', 'note'), 'Unsupported annotation type')
                dataset = 1 if kind == 'highlight' else 3
                start, end = r['start_position'], r['end_position']
                for p in (start, end):
                    require(isinstance(p['shortPosition'], int) and p['shortPosition'] >= 0, 'Invalid numeric position')
                    require(struct.unpack('<BII', base64.b64decode(p['longPosition'], validate=True))[0] == 1, 'Invalid KFX long position')
                aid = 'kindle.' + kind + '-' + str(start['shortPosition'])
                payload = dict(book_data=book_data, created_time=r.get('created_time', now),
                               last_modified=r.get('modified_time', now), start_position=start, end_position=end,
                               position_type=0, type=kind.upper(), json_metadata=json.dumps({'note_text': r['text']} if kind == 'note' else {}))
                existing = c.execute('select * from server_view where annotation_id=? and dataset_id=?', (aid, book_id)).fetchone()
                if existing:
                    require(semantic(json.loads(existing['serialized_payload'])) == semantic(payload), 'Existing annotation conflict: ' + aid)
                    payload = json.loads(existing['serialized_payload'])
                    payload.update(start_position=start, end_position=end)
                pending = c.execute('select * from local_edit where annotation_id=? and dataset_id=?', (aid, book_id)).fetchone()
                if pending:
                    require(pending['action'] == 1 and semantic(json.loads(pending['serialized_payload'])) == semantic(payload), 'Pending annotation conflict: ' + aid)
                # A previous installation receipt prevents requeue after a consumed upload.
                tracked = previous and previous.get('book_id') == book_id and aid in previous.get('annotation_ids', [])
                if tracked:
                    require(existing or pending, 'Previously installed annotation disappeared; investigate rather than recreate')
                if not existing:
                    c.execute('insert into server_view values (?,?,?,?,?,?)', (dataset, book_id, aid, json.dumps(payload), payload['created_time'], payload['last_modified']))
                    added += 1
                if not pending and not tracked:
                    # Native note and highlight samples have distinct dirty flags.
                    payload['last_modified'] = now
                    c.execute('insert into local_edit values (?,?,?,?,?,?,?,?,?,?,?)',
                              (aid, 1, dataset, book_id, json.dumps(payload), 0 if kind == 'highlight' else 1,
                               payload['created_time'], now, 0, '', 0))
                    queued += 1
                ids.append(aid)
            for table in SCHEMA:
                before = set(tuple(x) for x in orig.execute('select * from ' + table))
                after = set(tuple(x) for x in c.execute('select * from ' + table))
                require(before <= after, 'Existing rows altered: ' + table)
                expected = added if table == 'server_view' else queued if table == 'local_edit' else 0
                require(len(after-before) == expected, 'Unexpected changes: ' + table)
            require(c.execute('pragma integrity_check').fetchone()[0] == 'ok', 'Prepared DB failed integrity')
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()
    return dict(book_id=book_id, annotation_ids=sorted(set(ids)), added=added, queued=queued,
                status='prepared', cloud_verified=False)


def prepare(args):
    snapdir = Path(args.snapshot)
    snap = read(snapdir / 'snapshot.json')
    require(digest(snapdir / 'backup.sqlite') == snap['backup_sha256'], 'Backup hash mismatch')
    out = output_dir(args.output)
    data = read(args.mapping)
    validate_mapping_snapshot(data, snap)
    previous = read(args.previous_receipt) if args.previous_receipt else None
    report = prepare_database(snapdir/'backup.sqlite', out/'prepared.sqlite', data, snap['firmware'], previous)
    report.update(snapshot=snap, snapshot_fingerprint=data['snapshot_fingerprint'], kfx_path=data['kfx_path'], kfx_sha256=data['kfx_sha256'],
                  prepared_sha256=digest(out/'prepared.sqlite'))
    write(out/'report.json', report)
    print('Prepared:', report['added'], 'native records;', report['queued'], 'uploads. Review', out/'report.json')


def install_files(report, candidate, transfer):
    snapshot = report['snapshot']
    validate_mapping_snapshot(report, snapshot)
    path = Path(snapshot['database'])
    check_quiescent(path)
    require(digest(path) == snapshot['backup_sha256'], 'Device changed since backup; inspect and prepare afresh')
    require(digest(candidate) == report['prepared_sha256'], 'Prepared DB hash mismatch')
    require(digest(report['kfx_path']) == report['kfx_sha256'], 'Target book changed')
    version = (Path(snapshot['storage'])/'system/version.txt').read_text().strip()
    require(version == snapshot['firmware'], 'Device firmware changed')
    with db(candidate) as c:
        validate_schema(c)
    check_quiescent(path)
    require(digest(path) == snapshot['backup_sha256'], 'Device changed before transfer')
    transfer(candidate, path)
    require(digest(path) == report['prepared_sha256'], 'Transfer readback failed; retain backup and investigate before sync')
    return dict(report, status='installed', installed_sha256=digest(path), cloud_verified=False)


def mtp_transfer(source, destination):
    mount = next((p for p in destination.parents if p.name.startswith('mtp:host=')), None)
    require(mount, 'Automatic installation supports GVFS MTP only')
    host = mount.name.removeprefix('mtp:host=')
    uri = 'mtp://' + host + '/' + quote(str(destination.relative_to(mount)), safe='/')
    subprocess.run(['gio', 'copy', str(source), uri], check=True)


def install(args):
    require(args.apply, 'Review report and obtain required authorization, then pass --apply')
    p = Path(args.prepared)
    receipt = p/'receipt.json'
    require(not receipt.exists(), 'Installation receipt already exists; verify instead of repeating installation')
    result = install_files(read(p/'report.json'), p/'prepared.sqlite', mtp_transfer)
    write(receipt, result)
    print('Installed and byte-verified; cloud delivery remains unverified.')


def verify(args):
    receipt = read(args.receipt)
    path = Path(receipt['snapshot']['database'])
    check_quiescent(path)
    with db(path) as c:
        validate_schema(c)
        pending, missing = [], []
        for aid in receipt['annotation_ids']:
            row = c.execute('select action,retry_count,dirty_flag from local_edit where annotation_id=? and dataset_id=?', (aid, receipt['book_id'])).fetchone()
            if row:
                pending.append(dict(annotation_id=aid, **dict(row)))
            if not c.execute('select 1 from server_view where annotation_id=? and dataset_id=?', (aid, receipt['book_id'])).fetchone():
                missing.append(aid)
    print(json.dumps({'status':'queued' if pending else 'cloud_confirmation_required',
                      'pending':pending, 'missing_local_records':missing, 'cloud_verified':False}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='stage', required=True)
    p = sub.add_parser('inspect'); p.add_argument('--storage'); p.add_argument('--output', required=True); p.set_defaults(run=inspect)
    p = sub.add_parser('map')
    for name in ('snapshot', 'notes', 'book-id', 'kfx', 'kfxlib', 'output'): p.add_argument('--'+name, required=True)
    p.add_argument('--choices'); p.add_argument('--parser', default=str(SKILL.parent/'book-notes-from-kindle/scripts/parse_kindle.py')); p.set_defaults(run=mapping)
    p = sub.add_parser('prepare')
    for name in ('snapshot', 'mapping', 'output'): p.add_argument('--'+name, required=True)
    p.add_argument('--previous-receipt'); p.set_defaults(run=prepare)
    p = sub.add_parser('install'); p.add_argument('--prepared', required=True); p.add_argument('--apply', action='store_true'); p.set_defaults(run=install)
    p = sub.add_parser('verify'); p.add_argument('--receipt', required=True); p.set_defaults(run=verify)
    args = parser.parse_args()
    args.run(args)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
