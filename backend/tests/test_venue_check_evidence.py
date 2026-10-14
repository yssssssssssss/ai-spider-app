import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.venue_check_evidence import CheckEvidenceBuilder, context_crop, valid_box


class CheckEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.venue = {'venue_id': 'venue-1', 'record_id': 'r1', 'project_id': 'p1'}
        self.screens = []
        for number in (1, 2):
            file = f'screen-{number}.png'
            Image.new('RGB', (390, 844), ('white', 'pink')[number-1]).save(self.root / file)
            self.screens.append({'number': number, 'file': file, 'width': 390, 'height': 844,
                                 'sha256': self.sha(file)})
        self.capture = {'screens': self.screens}
        self.builder = CheckEvidenceBuilder(self.root)
        self.check = {'rule_id': 'OV-017', 'status': 'fail', 'enabled': True,
                      'evidence': [self.evidence([7, 119, 383, 153])]}

    def sha(self, file):
        return hashlib.sha256((self.root / file).read_bytes()).hexdigest()

    def evidence(self, box, screen=1):
        s = self.screens[screen-1]
        return {'screen': screen, 'file': s['file'], 'sha256': s['sha256'], 'bbox_px': box}

    def prepare(self, check=None):
        return self.builder.prepare(check or self.check, self.capture, self.venue)

    def live_spacing(self, gap=8, verified=True):
        Image.new('RGB', (390, 844), 'blue').save(self.root / 'live.png')
        dom = {'venue': self.venue, 'measurement': {
            'source': {'viewport_css_px': {'width': 390, 'height': 844}, 'visual_viewport': {'scale': 1}},
            'elements': [
                {'id': 'upper-module', 'status': 'measured', 'rect_css_px': {'left': 0, 'right': 390, 'top': 200, 'bottom': 400}},
                {'id': 'category-tabs', 'status': 'measured', 'rect_css_px': {'left': 0, 'right': 390, 'top': 400+gap, 'bottom': 450+gap}}
            ]}}
        (self.root / 'dom.json').write_text(json.dumps(dom))
        self.check.update(rule_id='OV-009', facts={'screenshot_file': 'live.png', 'screenshot_sha256': self.sha('live.png'),
            'dom_file': 'dom.json', 'dom_sha256': self.sha('dom.json'), 'measurement_status': 'measured',
            'semantic_boundary_verified': verified, 'upper_module': '权益', 'distance_css_px': gap})
        return dom

    def test_title_box_is_preserved_and_crop_has_context(self):
        before = copy.deepcopy(self.check)
        details = self.prepare()
        self.assertEqual(details['state'], 'localized')
        item, = details['items']
        self.assertEqual(item['marks'][0]['bbox_px'], [7, 119, 383, 153])
        self.assertEqual(item['crop_px'], [0, 81, 390, 191])
        self.assertEqual(self.check, before, 'Display cannot change an audit conclusion')

    def test_multiple_people_group_on_the_same_screenshot(self):
        self.check['evidence'] = [self.evidence([169, 83, 232, 174]), self.evidence([226, 81, 293, 175])]
        item, = self.prepare()['items']
        self.assertEqual(len(item['marks']), 2)
        self.assertEqual(item['file'], 'screen-1.png')
        self.assertTrue(valid_box(item['crop_px'], [390, 844]))

    def test_two_screens_never_mix_boxes(self):
        self.check['evidence'].append(self.evidence([200, 500, 250, 560], 2))
        first, second = self.prepare()['items']
        self.assertEqual(first['file'], 'screen-1.png')
        self.assertEqual(second['file'], 'screen-2.png')
        self.assertEqual(second['marks'][0]['bbox_px'], [200, 500, 250, 560])

    def test_tiny_pixel_sample_keeps_exact_size_and_visible_context(self):
        self.check.update(rule_id='OV-010', evidence=[self.evidence([0, 523, 3, 526])])
        item, = self.prepare()['items']
        self.assertEqual(item['marks'][0]['bbox_px'], [0, 523, 3, 526])
        self.assertEqual(item['crop_px'][2], 180)
        self.assertEqual(item['crop_px'][3]-item['crop_px'][1], 110)

    def test_whole_frame_evidence_has_no_issue_box(self):
        self.check['evidence'] = [self.evidence([0, 0, 390, 844])]
        result = self.prepare()
        self.assertEqual(result['state'], 'context')
        self.assertEqual(result['items'][0]['marks'], [])

    def test_missing_evidence_only_gets_reference_images(self):
        self.check.update(status='uncertain', evidence=[])
        result = self.prepare()
        self.assertEqual(result['state'], 'missing')
        self.assertEqual(len(result['items']), 2)
        self.assertTrue(all(not item['marks'] for item in result['items']))

    def test_disabled_rule_stays_hidden(self):
        self.check.update(enabled=False, status='disabled')
        self.assertEqual(self.prepare()['items'], [])

    def test_wrong_screenshot_hash_or_file_is_rejected(self):
        for field, value in [('sha256', 'fake'), ('file', 'screen-2.png')]:
            with self.subTest(field=field):
                check = copy.deepcopy(self.check); check['evidence'][0][field] = value
                with self.assertRaises(ValueError): self.prepare(check)

    def test_invalid_boxes_cannot_be_rendered(self):
        for box in ([0, 10, 391, 20], [0, 10, 1, 10], [0, -1, 1, 20], [0, 1, float('nan'), 20], [False, 1, 10, 20]):
            with self.subTest(box=box):
                check = copy.deepcopy(self.check); check['evidence'][0]['bbox_px'] = box
                with self.assertRaises(ValueError): self.prepare(check)

    def test_crop_is_clipped_to_edges_without_shifting_marks(self):
        crop = context_crop([[380, 838, 390, 844]], [390, 844])
        self.assertEqual(crop, [210, 734, 390, 844])

    def test_paths_cannot_escape_report_root(self):
        with self.assertRaises(ValueError): self.builder.path('../other.png')
        with self.assertRaises(ValueError): self.builder.path(str(self.root / 'screen-1.png'))

    def test_spacing_uses_matching_live_screenshot_and_dom_boundaries(self):
        self.live_spacing(8)
        result = self.prepare(); item, = result['items']
        self.assertEqual(item['file'], 'live.png')
        self.assertEqual(item['source'], 'live_h5_dom')
        self.assertEqual([m['start_px'][1] for m in item['marks'] if m['kind']=='line'], [400, 408])
        self.assertEqual(result['state'], 'localized')

    def test_zero_gap_preserves_coincident_lines_without_zero_height_rect(self):
        self.live_spacing(0)
        item, = self.prepare()['items']
        self.assertEqual([m['kind'] for m in item['marks']], ['line', 'line'])
        self.assertEqual(item['marks'][0]['start_px'], item['marks'][1]['start_px'])

    def test_ambiguous_dom_geometry_is_labeled_candidate(self):
        self.live_spacing(16, verified=False)
        result = self.prepare()
        self.assertEqual(result['state'], 'candidate')
        self.assertIn('仍待确认', result['items'][0]['label'])

    def test_live_identity_and_coordinate_scale_are_checked(self):
        for target in ('venue', 'scale', 'gap'):
            with self.subTest(target=target):
                dom = self.live_spacing()
                if target == 'venue': dom['venue'] = {'venue_id': 'another'}
                elif target == 'scale': dom['measurement']['source']['visual_viewport']['scale'] = 2
                else: dom['measurement']['elements'][1]['rect_css_px']['top'] += 1
                (self.root / 'dom.json').write_text(json.dumps(dom)); self.check['facts']['dom_sha256'] = self.sha('dom.json')
                with self.assertRaises(ValueError): CheckEvidenceBuilder(self.root).prepare(self.check, self.capture, self.venue)


if __name__ == '__main__':
    unittest.main()
