import copy
import hashlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).with_name('update_catalog.py'))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class CatalogTests(unittest.TestCase):
    def validated(self):
        image = Image.new('RGBA', (60, 40))
        ImageDraw.Draw(image).polygon([(3, 3), (55, 3), (47, 35), (9, 29)], fill=(40, 60, 80, 255))
        stream = io.BytesIO(); image.save(stream, format='PNG'); data = stream.getvalue()
        source = {'path': 'rear.png', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'width': 60, 'height': 40}
        return {'model': {'id': 'dse', 'kind': 'controller', 'images': {'rear': source}, 'controller': {'effectiveStyles': {'rearMirror': True}}}, 'members': {'rear.png': data}}

    def previous(self):
        return {'revision': 'old', 'package': {'url': 'https://github.com/PZ099/input-showcase/releases/download/models-1.0.6/controller-dse-old.zip', 'bytes': 3, 'sha256': 'a' * 64}}

    def test_minimum_client_is_1012(self):
        result = publisher.merge_catalog({'schemaVersion': 1, 'models': [], 'minimumClientVersion': '1.0.6'}, [])
        self.assertEqual(result['minimumClientVersion'], '1.0.12')

    def test_higher_minimum_is_not_lowered(self):
        result = publisher.merge_catalog({'schemaVersion': 1, 'models': [], 'minimumClientVersion': '1.0.20'}, [])
        self.assertEqual(result['minimumClientVersion'], '1.0.20')

    def test_provided_rear_matches_actual_mirrored_source(self):
        validated = self.validated(); data = publisher.outline_preview(validated, True)
        result = publisher.provided_rear_preview(data, {'size': len(data), 'browser_download_url': 'https://example.invalid/rear.png'}, validated)
        self.assertEqual(result['sourceSha256'], validated['model']['images']['rear']['sha256'])
        self.assertTrue(result['rearMirror'])

    def test_front_or_wrong_rear_is_rejected(self):
        validated = self.validated(); data = publisher.outline_preview(validated, True)
        image = publisher.png(data); image.putpixel((0, 0), (255, 0, 0, 255)); stream = io.BytesIO(); image.save(stream, format='PNG'); wrong = stream.getvalue()
        with self.assertRaises(ValueError):
            publisher.provided_rear_preview(wrong, {'size': len(wrong), 'browser_download_url': 'https://example.invalid/rear.png'}, validated)

    def test_unchanged_verified_rear_is_retained(self):
        validated = self.validated(); website = {'cloudRevision': 'old', 'rear': 'assets/rear.png', 'rearWidth': 256, 'rearHeight': 192}
        with patch.object(publisher, 'fetch_asset', return_value=b'old'), patch.object(publisher, 'validate_package', return_value=copy.deepcopy(validated)):
            result = publisher.retained_rear_preview(validated, self.previous(), website, 2)
        self.assertEqual(result['url'], website['rear'])
        self.assertEqual(result['retainedFromRevision'], 'old')

    def test_changed_source_or_mirror_cannot_retain_old_rear(self):
        validated = self.validated(); before = copy.deepcopy(validated); before['model']['controller']['effectiveStyles']['rearMirror'] = False
        website = {'cloudRevision': 'old', 'rear': 'assets/rear.png'}
        with patch.object(publisher, 'fetch_asset', return_value=b'old'), patch.object(publisher, 'validate_package', return_value=before):
            self.assertIsNone(publisher.retained_rear_preview(validated, self.previous(), website, 2))

    def test_unknown_previous_revision_cannot_retain_rear(self):
        self.assertIsNone(publisher.retained_rear_preview(self.validated(), self.previous(), {'cloudRevision': 'different', 'rear': 'assets/rear.png'}, 2))

    def test_schematic_flags_are_projected_without_inventing_defaults(self):
        entry = {'kind': 'controller', 'id': 'dse', 'name': 'Edge', 'brand': 'Sony', 'familyKey': 'controller:sony', 'familyName': 'Sony', 'versionName': 'Edge', 'revision': 'new', 'minimumRendererVersion': 2, 'preview': {'url': 'front.png', 'width': 256, 'height': 192}, 'web': {'frontSchematic': True, 'rearSchematic': True}}
        result = publisher.merge_website({'models': []}, {'models': [entry]}, {})['models'][0]
        self.assertTrue(result['frontSchematic']); self.assertTrue(result['rearSchematic'])
        del entry['web']
        result = publisher.merge_website({'models': []}, {'models': [entry]}, {})['models'][0]
        self.assertNotIn('frontSchematic', result); self.assertNotIn('rearSchematic', result)


if __name__ == '__main__':
    unittest.main()
