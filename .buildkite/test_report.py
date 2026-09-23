import unittest
from unittest.mock import patch

from report import STAGES, complete, main, render, statuses_for


def snapshot(state='finished', outcome='passed'):
    return {key: {'state': state, 'outcome': outcome} for key in STAGES}


class ReportTests(unittest.TestCase):
    def test_all_checks_must_pass(self):
        statuses = statuses_for(snapshot())
        markdown, style = render(statuses)
        self.assertEqual(style, 'success')
        self.assertIn('11/11 checks passed', markdown)
        self.assertIn('VERIFIED', markdown)
        self.assertIn('artifact://dist/*.whl', markdown)
        self.assertTrue(complete(statuses))

    def test_failed_gate_blocks_descendants_but_waits_for_siblings(self):
        steps = snapshot('waiting_for_dependencies', None)
        steps['prepare'] = {'state': 'finished', 'outcome': 'passed'}
        steps['lint'] = {'state': 'finished', 'outcome': 'hard_failed'}
        steps['format'] = {'state': 'ready', 'outcome': None}
        steps['types'] = {'state': 'running', 'outcome': None}
        steps['secrets'] = {'state': 'finished', 'outcome': 'passed'}
        statuses = statuses_for(steps)
        self.assertEqual(statuses['format'], 'queued')
        self.assertEqual(statuses['types'], 'running')
        self.assertEqual(statuses['iterators'], 'blocked')
        self.assertEqual(statuses['metadata'], 'blocked')
        self.assertFalse(complete(statuses))
        markdown, style = render(statuses)
        self.assertEqual(style, 'error')
        self.assertIn('2/11 checks passed', markdown)
        self.assertIn('6 blocked', markdown)
        self.assertIn('artifact://reports/lint.txt', markdown)
        self.assertNotIn('artifact://dist/', markdown)
        self.assertIn('LIVE', markdown)

        for key in ('format', 'types'):
            steps[key] = {'state': 'finished', 'outcome': 'passed'}
        statuses = statuses_for(steps)
        self.assertTrue(complete(statuses))
        self.assertIn('STOPPED', render(statuses)[0])

    def test_waiting_is_not_blocked_without_a_failed_dependency(self):
        steps = snapshot('waiting_for_dependencies', None)
        steps['prepare'] = {'state': 'running', 'outcome': None}
        statuses = statuses_for(steps)
        self.assertEqual(statuses['lint'], 'pending')
        self.assertFalse(complete(statuses))
        self.assertEqual(render(statuses)[1], 'info')

    def test_terminal_states_never_masquerade_as_success(self):
        for state, outcome, expected in [
            ('finished', 'errored', 'failed'),
            ('finished', 'dependency_failed', 'blocked'),
            ('finished', 'soft_failed', 'failed'),
            ('canceled', None, 'canceled'),
            ('ignored', None, 'skipped'),
        ]:
            with self.subTest(state=state, outcome=outcome):
                steps = snapshot()
                steps['metadata'] = {'state': state, 'outcome': outcome}
                statuses = statuses_for(steps)
                self.assertEqual(statuses['metadata'], expected)
                self.assertTrue(complete(statuses))
                self.assertEqual(render(statuses)[1], 'error')

    def test_missing_check_is_not_green(self):
        steps = snapshot()
        del steps['metadata']
        statuses = statuses_for(steps)
        self.assertEqual(statuses['metadata'], 'unknown')
        self.assertFalse(complete(statuses))
        self.assertNotEqual(render(statuses)[1], 'success')

    def test_interrupted_reporting_is_explicit_and_escaped(self):
        markdown, style = render(
            dict.fromkeys(STAGES, 'passed'), notice='Cannot poll <API>'
        )
        self.assertEqual(style, 'warning')
        self.assertIn('STALE', markdown)
        self.assertIn('Cannot poll &lt;API&gt;', markdown)
        self.assertNotIn('VERIFIED', markdown)

    def test_polls_until_last_check_finishes_without_watching_itself(self):
        active = snapshot()
        active['install'] = {'state': 'running', 'outcome': None}
        snapshots = [active, snapshot()]
        with (
            patch(
                'report.step_for', side_effect=lambda key: snapshots[0][key]
            ),
            patch('report.time.sleep', side_effect=lambda _: snapshots.pop(0)),
            patch('report.publish') as publish,
        ):
            main()
        self.assertEqual(publish.call_count, 2)
        self.assertEqual(
            publish.call_args_list[0].args[0]['install'], 'running'
        )
        self.assertTrue(complete(publish.call_args_list[1].args[0]))
        self.assertNotIn('report', publish.call_args.args[0])

    def test_timeout_publishes_stale_status_and_exits(self):
        with (
            patch('report.time.monotonic', side_effect=[0, 541]),
            patch('report.publish') as publish,
            self.assertRaisesRegex(SystemExit, 'nine minutes'),
        ):
            main()
        self.assertIn('timed out', publish.call_args.args[1])
