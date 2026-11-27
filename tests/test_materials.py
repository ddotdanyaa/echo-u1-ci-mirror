import os
from pathlib import Path
import tempfile
import unittest
import zipfile

try:
    from echo_sync.materials import import_materials
except ImportError:
    import_materials = None

class MaterialsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(import_materials, 'Material import is not implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.safe = lambda: {'file_tools': {'hosted_ocr': False}}

    def test_unicode_text_and_headers_and_backup(self):
        source = self.home/'текст.txt'
        source.write_bytes('Русский материал'.encode('utf-16'))
        first = import_materials([source], self.home)
        self.assertIn('Русский материал', first['path'].read_text(encoding='utf-8'))
        source.write_bytes(b'\xef\xbb\xbfNew material')
        result = import_materials([source], self.home)
        self.assertIn('New material', result['path'].read_text(encoding='utf-8'))
        self.assertIn('Русский материал', result['backup'].read_text(encoding='utf-8'))
        self.assertEqual(result['files'], 1)

    def test_all_files_success_before_commit(self):
        dest=self.home/'materials/context.md';dest.parent.mkdir();dest.write_text('old')
        a=self.home/'a.txt';a.write_text('new')
        b=self.home/'b.pdf';b.write_bytes(b'example')
        def fail(_): raise ValueError('cannot extract')
        with self.assertRaisesRegex(ValueError,'cannot extract'):
            import_materials([a,b],self.home,extract=fail,config=self.safe)
        self.assertEqual(dest.read_text(),'old')
        self.assertEqual(list(dest.parent.glob('*.bak')),[])

    def test_document_callback_requires_explicit_false_not_missing_or_zero(self):
        path=self.home/'book.docx';path.write_bytes(b'example')
        for cfg in [{},{'file_tools': {'hosted_ocr': True}},{'file_tools': {'hosted_ocr': 0}}]:
            called=[]
            with self.subTest(cfg=cfg),self.assertRaisesRegex(ValueError,'hosted_ocr'):
                import_materials([path],self.home,extract=lambda p:called.append(p),config=lambda:cfg)
            self.assertEqual(called,[])

    def test_injected_document_extractor_and_oversize_fail_closed(self):
        path=self.home/'slides.pptx';path.write_bytes(b'example')
        result=import_materials([path],self.home,extract=lambda p:'Extracted slides',config=self.safe)
        self.assertIn('Extracted slides',result['path'].read_text())
        before=result['path'].read_bytes()
        with self.assertRaisesRegex(ValueError,'180000'):
            import_materials([path],self.home,extract=lambda p:'x'*180001,config=self.safe)
        self.assertEqual(result['path'].read_bytes(),before)

    def test_empty_and_unsupported_rejected(self):
        for name in ['empty.txt','image.png']:
            source=self.home/name;source.write_bytes(b'')
            with self.assertRaises(ValueError):import_materials([source],self.home)

    @unittest.skipUnless(os.environ.get('HERMES_SOURCE'),'HERMES_SOURCE not set: real Hermes DOCX extraction not available')
    def test_actual_hermes_stdlib_docx(self):
        import sys
        sys.path.insert(0,os.environ['HERMES_SOURCE'])
        path=self.home/'source.docx'
        with zipfile.ZipFile(path,'w') as doc:
            doc.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Русский документ</w:t></w:r></w:p></w:body></w:document>')
        result=import_materials([path],self.home,config=self.safe)
        self.assertIn('Русский документ',result['path'].read_text(encoding='utf-8'))

    def test_scanned_missing_text_warning_is_rejected(self):
        path=self.home/'scan.pdf';path.write_bytes(b'example')
        for marker in ['[NEEDS OCR: missing pages]', '[EXTRACTION COVERAGE WARNING: missing pages]']:
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError,'OCR'):
                import_materials([path],self.home,extract=lambda p:marker,config=self.safe)

    def test_registered_cli_imports_into_resolved_profile_home(self):
        import argparse
        import contextlib
        import io
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from echo_sync.plugin import register
        commands={}
        ctx=SimpleNamespace(get_config=lambda k,d:d,register_hook=lambda *a:None,register_middleware=lambda *a:None,register_cli_command=lambda name,description,setup,callback:commands.update({name:(setup,callback)}))
        with patch.dict(sys.modules,{'hermes_constants':SimpleNamespace(get_hermes_home=lambda:self.home)}):
            register(ctx)
            self.assertIn('echo-import',commands,'echo-import CLI was not registered')
            parser=argparse.ArgumentParser()
            setup,callback=commands['echo-import'];setup(parser)
            source=self.home/'notes.md';source.write_text('Material without provider calls')
            stream=io.StringIO()
            with contextlib.redirect_stdout(stream):callback(parser.parse_args([str(source)]))
            self.assertIn('context.md',stream.getvalue())
            self.assertIn('Material without provider calls',(self.home/'materials/context.md').read_text())
