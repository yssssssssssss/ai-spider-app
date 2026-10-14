"""User-approved ranges must not turn missing evidence or skipped checks into passes."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services.visual_measurement import compare_length_range
from scripts.build_venue_recheck_report import venue_status
from scripts.recheck_tab_spacing import classify_spacing
from scripts.apply_tab_spacing_reviews import apply


class TabSpacingReviewTests(unittest.TestCase):
    def setUp(self):
        self.policy = {'acceptable_range_px': {'min': 7, 'max': 9, 'unit': 'css_px'},
                       'skip_when_gray_demo_floor': True, 'user_confirmed_skip_venue_ids': ['furniture']}

    def test_both_endpoints_pass_and_outside_values_fail_without_rounding(self):
        for gap, expected in [(7, 'pass'), (8, 'pass'), (9, 'pass'), (6.999, 'fail'), (9.001, 'fail'), (0, 'fail'), (16, 'fail'), (-0.5, 'fail')]:
            with self.subTest(gap=gap):
                review = {'venue': {'venue_id': 'normal'}, 'measurement_status': 'measured',
                          'semantic_boundary_verified': True, 'distance_css_px': gap}
                self.assertEqual(classify_spacing(review, self.policy), expected)

    def test_nonfinite_values_cannot_pass(self):
        for invalid in [float('nan'), float('inf'), True, '8']:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                compare_length_range(invalid, min_px=7, max_px=9)
        with self.assertRaises(ValueError):
            compare_length_range(8, min_px=9, max_px=7)

    def test_a_candidate_eight_pixel_band_is_not_a_verified_pass(self):
        review = {'venue': {'venue_id': 'normal'}, 'measurement_status': 'measured',
                  'semantic_boundary_verified': False, 'distance_css_px': 8}
        self.assertEqual(classify_spacing(review, self.policy), 'uncertain')
        review['measurement_status'] = 'missing'
        self.assertEqual(classify_spacing(review, self.policy), 'uncertain')

    def test_gray_demo_and_confirmed_furniture_are_skipped_not_passed(self):
        for venue, reason in [('normal', '灰色示意楼层'), ('furniture', '用户确认楼层异常提示也跳过')]:
            review = {'venue': {'venue_id': venue}, 'measurement_status': 'skipped', 'skip_reason': reason}
            self.assertEqual(classify_spacing(review, self.policy), 'not_applicable')
        review = {'venue': {'venue_id': 'unconfirmed'}, 'measurement_status': 'skipped', 'skip_reason': '灰色背景'}
        self.assertEqual(classify_spacing(review, self.policy), 'uncertain')

    def test_venue_states_are_mutually_exclusive_and_inactive_checks_do_not_block(self):
        audit = {'page_state': 'ready', 'mandatory_fail_count': 0,
                 'checks': [{'status': 'uncertain', 'enabled': False}]}
        self.assertEqual(venue_status(audit), 'partial_inspection')
        audit['checks'].append({'status': 'uncertain', 'enabled': True})
        self.assertEqual(venue_status(audit), 'needs_confirmation')
        audit['mandatory_fail_count'] = 1
        self.assertEqual(venue_status(audit), 'visible_issues')
        audit['page_state'] = 'error'
        self.assertEqual(venue_status(audit), 'page_error')
        self.assertEqual(venue_status(None), 'pending')

    def test_spacing_cannot_modify_an_incomplete_visual_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'specification').mkdir()
            (root / 'specification/walkthrough.json').write_text(json.dumps({'spacing': self.policy}))
            (root / 'catalog.json').write_text(json.dumps({'venues': [{'record_id': 'ready', 'venue_id': 'ready'}, {'record_id': 'pending', 'venue_id': 'pending'}]}))
            ready = root / 'venues/ready'
            ready.mkdir(parents=True)
            audit = ready / 'audit.json'
            audit.write_text('{"unchanged":true}')
            before = audit.read_bytes()
            with self.assertRaisesRegex(ValueError, 'Finish all visual audits'):
                apply(root)
            self.assertEqual(audit.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
