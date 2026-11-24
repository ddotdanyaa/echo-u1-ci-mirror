import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from echo_sync.materials import import_materials
from echo_sync.plugin import EchoPlugin


class MaterialProvenanceTests(unittest.TestCase):
    def test_metadata_only_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td); source = home/'notes.txt'; source.write_text('Проверенный материал', encoding='utf-8')
            imported = import_materials([source], home)
            content = imported['path'].read_text(encoding='utf-8')
            old_hash = imported['manifest']['sources'][0]['source_hash']
            imported['path'].write_text(content.replace(old_hash, 'f'*64), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                EchoPlugin(home)._context()

    def test_crlf_source_has_stable_canonical_text_and_integrity_on_restart(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td); source = home/'notes.txt'
            source.write_bytes('Первая строка\r\nВторая строка\r\n'.encode('utf-8'))
            imported = import_materials([source], home)
            self.assertIn('Первая строка\nВторая строка', EchoPlugin(home)._context())
            self.assertEqual(imported['manifest']['sources'][0]['source_hash'], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_import_has_versioned_provenance_in_same_atomic_context(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td); source = home/'notes.txt'
            source.write_text('Проверенный учебный материал', encoding='utf-8')
            imported = import_materials([source], home)
            manifest = imported.get('manifest')
            self.assertIsInstance(manifest, dict)
            self.assertEqual(manifest['schema_version'], 1)
            self.assertEqual(manifest['sources'][0]['source_hash'], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(manifest['sources'][0]['source_name'], 'notes.txt')
            self.assertNotIn(str(home), json.dumps(manifest))
            self.assertIn('updated_at', manifest)
            context = imported['path'].read_text(encoding='utf-8')
            self.assertTrue(context.startswith('<!-- ECHO_MATERIALS_V1 '))
            self.assertIn(manifest['sources'][0]['source_hash'], context)
            self.assertEqual(EchoPlugin(home)._context(), context)

    def test_changed_material_gets_new_content_version_and_exact_backup(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td); source = home/'notes.txt'; source.write_text('Версия один', encoding='utf-8')
            first = import_materials([source], home)
            before = first['path'].read_bytes()
            source.write_text('Версия два', encoding='utf-8')
            second = import_materials([source], home)
            self.assertNotEqual(first.get('manifest'), second.get('manifest'))
            self.assertEqual(second['backup'].read_bytes(), before)

    def test_corrupted_context_is_not_sent_to_generation(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td); source = home/'notes.txt'; source.write_text('Подлинный материал', encoding='utf-8')
            imported = import_materials([source], home)
            body = imported['path'].read_text(encoding='utf-8')
            imported['path'].write_text(body.replace('Подлинный', 'Подменённый'), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'integrity'):
                EchoPlugin(home)._context()

    def test_legacy_context_remains_readable_after_restart(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td); folder = home/'materials'; folder.mkdir()
            (folder/'context.md').write_text('Старый формат без manifest', encoding='utf-8')
            self.assertEqual(EchoPlugin(home)._context(), 'Старый формат без manifest')

    def test_manifest_handles_each_document_format_without_claiming_real_extraction(self):
        # Injected extraction tests the manifest adapter only. Real format
        # extraction/QA is a separate integration gate.
        for suffix in ('.docx', '.pdf', '.pptx'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as td:
                home = Path(td); source = home/('fixture'+suffix); source.write_bytes(b'offline fixture')
                imported = import_materials([source], home, extract=lambda _: 'Извлечённый текст',
                                            config=lambda: {'file_tools': {'hosted_ocr': False}})
                self.assertEqual(imported.get('manifest', {}).get('sources', [{}])[0].get('format'), suffix[1:])


if __name__ == '__main__':
    unittest.main()
