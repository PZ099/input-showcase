import copy
import hashlib
import importlib.util
import io
import json
import zipfile
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

    def test_minimum_client_is_1014(self):
        result = publisher.merge_catalog({'schemaVersion': 1, 'models': [], 'minimumClientVersion': '1.0.6'}, [])
        self.assertEqual(result['minimumClientVersion'], '1.0.14')

    def test_higher_minimum_is_not_lowered(self):
        result = publisher.merge_catalog({'schemaVersion': 1, 'models': [], 'minimumClientVersion': '1.0.20'}, [])
        self.assertEqual(result['minimumClientVersion'], '1.0.20')

    def controller_package(self, front_actions, rear_actions, rear_traces=None, bumpers=None):
        validated = self.validated(); data = validated['members']['rear.png']
        desc = dict(validated['model']['images']['rear'])
        profile = {'Id': 'fixture'}
        profile.update({key: [] for key in ('Positions', 'BackPhysicalSurfaces', 'Extras', 'RearExtras', 'FrontExtras')})
        profile.update({key: {'x': .5, 'y': .5} for key in ('LS', 'RS', 'Dpad', 'Face', 'Back', 'Start')})
        section = {'profile': profile, 'buttonMetrics': {'Id': 'fixture', 'FaceX': .02, 'FaceY': .02, 'MenuWidth': .03, 'MenuHeight': .02},
            'frontShoulders': [[], []], 'rearTriggers': rear_traces or [],
            'backGeometry': {'id': 'fixture', 'sourceKind': 'none', 'backs': [], 'labelCenters': []},
            'feedback': {'bumperActions': ['lb', 'lt'] if bumpers is None else bumpers,
                'frontSecondaryActions': front_actions, 'rearTriggerActions': rear_actions},
            'effectiveStyles': {'dpadKind': 'disc', 'faceLabels': ['A', 'B', 'X', 'Y'], 'menuLabels': ['-', '+']}, 'paths': {}}
        model = {'schemaVersion': 1, 'kind': 'controller', 'id': 'fixture', 'revision': 'test', 'minimumRendererVersion': 2,
            'metadata': {'name': 'Fixture', 'brand': 'Test', 'familyKey': 'controller:fixture', 'familyName': 'Fixture', 'versionName': 'One'},
            'images': {'front': desc}, 'files': [{'path': 'rear.png', 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}], 'controller': section}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('model.json', json.dumps(model)); archive.writestr('rear.png', data)
        raw = stream.getvalue()
        return raw, {'name': 'controller-fixture-test.zip', 'size': len(raw), 'browser_download_url': 'https://example.invalid/fixture.zip'}

    def test_explicit_absent_trigger_feedback_is_supported(self):
        raw, asset = self.controller_package([], [])
        result = publisher.validate_package(raw, asset, 2)
        self.assertEqual(result['model']['controller']['feedback']['frontSecondaryActions'], [])

    def test_absent_feedback_cannot_hide_existing_rear_trace(self):
        raw, asset = self.controller_package([], [], rear_traces=[[[.1, .1], [.2, .1], [.2, .2]]])
        with self.assertRaises(ValueError):
            publisher.validate_package(raw, asset, 2)

    def test_empty_or_partial_action_strings_remain_invalid(self):
        for front, rear, bumpers in [(['', ''], [], None), (['lt'], [], None), ([], [], [])]:
            raw, asset = self.controller_package(front, rear, bumpers=bumpers)
            with self.assertRaises(ValueError):
                publisher.validate_package(raw, asset, 2)

    def test_large_rgba_preview_pixels_remain_compatible_across_pillow_versions(self):
        image = Image.new('RGBA', (2048, 1024)); draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((70, 60, 1900, 970), 120, fill=(60, 70, 90, 250))
        for k in range(20, 2000, 17):
            draw.line((k, 5, max(0, k - 480), 1010), fill=(k % 255, 120, (k * 3) % 255, 80 + k % 170), width=3)
        stream = io.BytesIO(); image.save(stream, format='PNG')
        validated = {'model': {'id': 'preview-regression', 'kind': 'controller',
            'images': {'rear': {'path': 'rear.png'}}, 'controller': {'effectiveStyles': {'rearMirror': True}}},
            'members': {'rear.png': stream.getvalue()}}
        with publisher.png(publisher.outline_preview(validated, True)) as preview:
            self.assertEqual(preview.size, (256, 192))
            self.assertEqual(hashlib.sha256(preview.tobytes()).hexdigest(),
                '8aa4867c1101eba5938923b3e18dbbe0cee57f773aecd495fda2682af3582e02')

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
