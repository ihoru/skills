import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('kindle_import', ROOT/'scripts/kindle_import.py')
k = importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
BOOK = 'SYNTHETIC-PDOC-CR!EXAMPLE-1'


def fixture(path):
    c = sqlite3.connect(path)
    ints = {'action','dataset','dirty_flag','created_time','modified_time','retry_count','sync_behavior','state','migration_state'}
    for name, cols in k.SCHEMA.items():
        definitions = [col + (' INTEGER' if col in ints else ' TEXT') + ' NOT NULL' for col in cols]
        if name in ('local_edit','server_view','staging_server_view'):
            definitions.append('PRIMARY KEY(annotation_id,dataset_id)')
        c.execute('CREATE TABLE '+name+'('+','.join(definitions)+')')
    c.execute('INSERT INTO book_state VALUES (?,?)',(BOOK,0))
    c.execute('INSERT INTO key_value_storage VALUES (?,?)',('unrelated','preserve me'))
    c.commit(); c.close()


def mapped():
    records=[{'id':1,'kind':'highlight','text':'café'}, {'id':2,'kind':'note','text':'my note','attach_to':1}]
    return {'book_id':BOOK,'records':k.map_records(records,[{'pid':10,'eid':3,'eid_offset':0,'text':'A café!'}])}


class MappingTests(unittest.TestCase):
    def test_unicode_and_attached_note(self):
        h,n=mapped()['records']
        self.assertEqual(h['start_position']['shortPosition'],12)
        self.assertEqual(h['end_position']['shortPosition'],15)
        self.assertEqual(n['start_position'],h['end_position'])
        self.assertEqual(n['text'],'my note')

    def test_reordered_duplicate_and_missing(self):
        chunks=[{'pid':30,'eid':4,'eid_offset':0,'text':'second café'},
                {'pid':0,'eid':2,'eid_offset':0,'text':'first café'}]
        r=[{'id':1,'kind':'highlight','text':'café'}, {'id':2,'kind':'note','text':'no anchor'}]
        out=k.map_records(r,chunks)
        self.assertEqual(out[0]['status'],'unresolved')
        self.assertEqual(len(out[0]['candidates']),2)
        self.assertEqual(out[1]['status'],'unresolved')
        out=k.map_records(r,chunks,{'1':{'candidate':2}})
        self.assertEqual(out[0]['start_position']['shortPosition'],37)
        self.assertEqual(k.map_records([{'id':1,'kind':'highlight','text':'absent'}],chunks)[0]['status'],'unresolved')

    def test_cross_chunk_punctuation(self):
        chunks=[{'pid':0,'eid':2,'eid_offset':0,'text':'“Hello '}, {'pid':7,'eid':3,'eid_offset':0,'text':'world.”'}]
        out=k.map_records([{'id':1,'kind':'highlight','text':'“Hello world.”'}],chunks)[0]
        self.assertEqual(out['matched_text'],'“Hello world.”')

    def test_canonical_unicode_runs(self):
        for text, query in [('cafe\u0301', 'café'), ('café', 'cafe\u0301'),
                            ('a\u0315\u0300', 'à\u0315'), ('Straße', 'STRASSE')]:
            chunks=[{'pid':i,'eid':i+1,'eid_offset':0,'text':ch} for i,ch in enumerate(text)]
            result=k.map_records([{'id':1,'kind':'highlight','text':query}],chunks)[0]
            self.assertEqual(result['status'],'mapped')
            self.assertEqual(result['start_position']['shortPosition'],0)
            self.assertEqual(result['end_position']['shortPosition'],len(text)-1)

    def test_gap_cannot_be_selected(self):
        for second in (4,1000):
            chunks=[{'pid':0,'eid':1,'eid_offset':0,'text':'foo'},
                    {'pid':second,'eid':2,'eid_offset':0,'text':'bar'}]
            r=[{'id':1,'kind':'highlight','text':'foo bar'}]
            result=k.map_records(r,chunks)[0]
            self.assertEqual(result['status'],'unresolved')
            self.assertEqual(result['candidates'],[])
            with self.assertRaises(ValueError):k.map_records(r,chunks,{'1':{'candidate':1}})


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.src=self.root/'source.sqlite';fixture(self.src)

    def tearDown(self): self.tmp.cleanup()

    def prep(self,source=None,data=None,previous=None,name='result.sqlite',firmware='Kindle 5.19.6 (example)'):
        dest=self.root/name
        report=k.prepare_database(source or self.src,dest,data or mapped(),firmware,previous)
        return dest,report

    def test_prepare_preserves_and_repeat(self):
        dest,report=self.prep()
        self.assertEqual((report['added'],report['queued']),(2,2))
        with sqlite3.connect(dest) as c:
            self.assertEqual(c.execute('select value from key_value_storage').fetchone()[0],'preserve me')
            flags=c.execute('select dataset,dirty_flag from local_edit order by dataset').fetchall()
            self.assertEqual(flags,[(1,0),(3,1)])
        dest2,report2=self.prep(dest,name='repeat.sqlite')
        self.assertEqual((report2['added'],report2['queued']),(0,0))
        with sqlite3.connect(dest2) as c:c.execute('delete from local_edit')
        _,report3=self.prep(dest2,previous=dict(report,status='installed'),name='after-sync.sqlite')
        self.assertEqual(report3['queued'],0)

    def test_queue_local_only(self):
        dest,_=self.prep()
        with sqlite3.connect(dest) as c:c.execute('delete from local_edit')
        _,r=self.prep(dest,name='local.sqlite')
        self.assertEqual((r['added'],r['queued']),(0,2))

    def test_conflict_and_preserve_newer_note(self):
        dest,_=self.prep();data=mapped();data['records'][1]['text']='overwrite newer note'
        with self.assertRaisesRegex(ValueError,'conflict'):self.prep(dest,data,name='conflict.sqlite')
        with sqlite3.connect(dest) as c:
            payload=c.execute('select serialized_payload from server_view where dataset=3').fetchone()[0]
            self.assertEqual(json.loads(json.loads(payload)['json_metadata'])['note_text'],'my note')

    def test_unsupported_and_unresolved(self):
        with self.assertRaisesRegex(ValueError,'Unsupported firmware'):self.prep(firmware='Kindle 6.0')
        with sqlite3.connect(self.src) as c:c.execute('create table unknown (id integer)')
        with self.assertRaisesRegex(ValueError,'Unrecognized schema'):self.prep(name='unknown.sqlite')
        data=mapped();data['records'][0]['status']='unresolved'
        with self.assertRaisesRegex(ValueError,'Resolve every'):self.prep(data=data,name='unresolved.sqlite')

    def test_transfer_checks(self):
        candidate,_=self.prep(); storage=self.root/'storage';(storage/'system').mkdir(parents=True)
        (storage/'system/version.txt').write_text('Kindle 5.19.6')
        book=self.root/'book.kfx';book.write_bytes(b'synthetic')
        report={'snapshot':{'database':str(self.src),'backup_sha256':k.digest(self.src),'storage':str(storage),'firmware':'Kindle 5.19.6','books':[BOOK],'kfx_files':[str(book)]},
                'prepared_sha256':k.digest(candidate),'kfx_path':str(book),'kfx_sha256':k.digest(book)}
        report['book_id']=BOOK
        report['snapshot_fingerprint']=k.snapshot_fingerprint(report['snapshot'])
        with self.assertRaisesRegex(ValueError,'readback failed'):
            k.install_files(report,candidate,lambda s,d:None)
        self.src.write_bytes(b'changed')
        called=[]
        with self.assertRaisesRegex(ValueError,'changed since backup'):
            k.install_files(report,candidate,lambda s,d:called.append(True))
        self.assertFalse(called)

    def test_empty_queue_not_cloud_proof(self):
        import contextlib, io
        from types import SimpleNamespace
        dest,report=self.prep()
        with sqlite3.connect(dest) as c:c.execute('delete from local_edit')
        receipt=self.root/'receipt.json'
        k.write(receipt,dict(report,snapshot={'database':str(dest)}))
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf):k.verify(SimpleNamespace(receipt=str(receipt)))
        result=json.loads(buf.getvalue())
        self.assertEqual(result['status'],'cloud_confirmation_required')
        self.assertFalse(result['cloud_verified'])

    def test_changed_long_positions_conflict(self):
        for table in ('server_view','local_edit'):
            dest,_=self.prep(name=table+'.sqlite')
            with sqlite3.connect(dest) as c:
                if table=='local_edit':c.execute('delete from server_view')
                payload=json.loads(c.execute('select serialized_payload from '+table+' where dataset=1').fetchone()[0])
                payload['end_position']['longPosition']=k.position(15,99,7)['longPosition']
                c.execute('update '+table+' set serialized_payload=? where dataset=1',(json.dumps(payload),))
            with self.assertRaisesRegex(ValueError,'conflict'):
                self.prep(dest,name=table+'-conflict.sqlite')

    def test_mapping_bound_to_snapshot(self):
        book=self.root/'book.kfx';book.write_bytes(b'edition one')
        snap={'books':[BOOK],'kfx_files':[str(book)],'database':'device-one/database', 'backup_sha256':'example'}
        mapping={'book_id':BOOK,'kfx_path':str(book),'kfx_sha256':k.digest(book),
                 'snapshot_fingerprint':k.snapshot_fingerprint(snap)}
        k.validate_mapping_snapshot(mapping,snap)
        with self.assertRaisesRegex(ValueError,'snapshot'):
            k.validate_mapping_snapshot(mapping,dict(snap,database='device-two/database'))
        with self.assertRaisesRegex(ValueError,'listed'):
            k.validate_mapping_snapshot(dict(mapping,kfx_path='another.kfx'),snap)
        book.write_bytes(b'edition two')
        with self.assertRaisesRegex(ValueError,'changed'):
            k.validate_mapping_snapshot(mapping,snap)

    def test_active_journal_blocks(self):
        Path(str(self.src)+'-wal').write_bytes(b'')
        with self.assertRaisesRegex(ValueError,'journal'):k.check_quiescent(self.src)


if __name__=='__main__':unittest.main()
