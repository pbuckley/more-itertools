import unittest

from report import STAGES, render


class ReportTests(unittest.TestCase):
    def test_all_checks_must_pass(self):
        markdown, style = render(dict.fromkeys(STAGES, 'passed'))
        self.assertEqual(style, 'success')
        self.assertIn('11/11 checks passed', markdown)

    def test_failure_and_unrun_checks_are_not_green(self):
        states = dict.fromkeys(STAGES, '')
        states.update(prepare='passed', lint='hard_failed')
        markdown, style = render(states)
        self.assertEqual(style, 'error')
        self.assertIn('1/11 checks passed', markdown)
        self.assertIn('| Lint | hard_failed |', markdown)
        self.assertIn('| Build wheel | not_run |', markdown)

    def test_missing_check_is_not_green(self):
        states = dict.fromkeys(STAGES, 'passed')
        del states['metadata']
        markdown, style = render(states)
        self.assertEqual(style, 'error')
        self.assertIn('| Metadata & checksums | unknown |', markdown)
