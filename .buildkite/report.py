import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import subprocess
import time


GROUPS = {
    '🌱 Prepare': {'prepare': 'Source & tools'},
    '🔎 Quality': {
        'lint': 'Lint',
        'format': 'Formatting',
        'types': 'Type contracts',
        'secrets': 'Secret scan',
    },
    '🧪 Tests': {'iterators': 'Iterators', 'recipes': 'Recipes'},
    '📦 Package': {'wheel': 'Wheel', 'sdist': 'Source archive'},
    '🚀 Verify': {'install': 'Install smoke', 'metadata': 'Metadata'},
}
STAGES = {
    key: label for group in GROUPS.values() for key, label in group.items()
}
STATUS = {
    'passed': ('✓', 'Passed', 'green'),
    'failed': ('✕', 'Failed', 'red'),
    'running': ('◉', 'Running', 'blue'),
    'queued': ('◷', 'Queued', 'blue'),
    'pending': ('○', 'Waiting', 'gray'),
    'blocked': ('↳', 'Blocked', 'gray'),
    'canceled': ('−', 'Canceled', 'orange'),
    'skipped': ('−', 'Skipped', 'gray'),
    'unknown': ('?', 'Unknown', 'orange'),
}
TERMINAL = {'passed', 'failed', 'blocked', 'canceled', 'skipped'}


def statuses_for(steps):
    statuses = {}
    dependency_failed = False
    for group in GROUPS.values():
        for key in group:
            step = steps.get(key, {})
            state, outcome = step.get('state'), step.get('outcome')
            if state == 'canceled':
                status = 'canceled'
            elif state == 'ignored':
                status = 'skipped'
            elif state == 'finished':
                status = {
                    'passed': 'passed',
                    'hard_failed': 'failed',
                    'soft_failed': 'failed',
                    'errored': 'failed',
                    'dependency_failed': 'blocked',
                    'neutral': 'skipped',
                }.get(outcome, 'unknown')
            elif state == 'waiting_for_dependencies':
                # Blocked jobs can retain this state with no terminal outcome.
                status = 'blocked' if dependency_failed else 'pending'
            else:
                status = {
                    'ready': 'queued',
                    'running': 'running',
                    'failing': 'running',
                }.get(state, 'unknown')
            statuses[key] = status
        dependency_failed |= any(
            statuses[key] in {'failed', 'blocked', 'canceled'} for key in group
        )
    return statuses


def complete(statuses):
    return all(statuses.get(key) in TERMINAL for key in STAGES)


def render(statuses, updated='just now', notice=''):
    counts = {
        status: sum(statuses.get(key) == status for key in STAGES)
        for status in STATUS
    }
    done = complete(statuses)
    passed = counts['passed']
    if notice:
        title, badge, color, style = (
            'Live reporting interrupted',
            'STALE',
            'orange',
            'warning',
        )
    elif passed == len(STAGES):
        title, badge, color, style = (
            'Release candidate verified',
            'VERIFIED',
            'green',
            'success',
        )
    elif done:
        title, badge, color, style = (
            'Repair required',
            'STOPPED',
            'red',
            'error',
        )
    elif counts['failed'] or counts['canceled']:
        title, badge, color, style = (
            'Failure detected · watching remaining checks',
            'LIVE',
            'red',
            'error',
        )
    else:
        title, badge, color, style = (
            'Release checks in progress',
            'LIVE',
            'blue',
            'info',
        )

    lines = [
        '<div class="p2">',
        '<div class="flex items-center justify-between flex-wrap mb2">',
        '<div><div class="h6 caps navy bold">more-itertools / release checks</div>',
        f'<div class="h2 bold mt1">{title}</div></div>',
        f'<span class="bg-{color} white rounded px2 py1 bold h6">{badge}</span></div>',
        '<div class="flex items-baseline flex-wrap mb2">',
        f'<span class="h2 bold mr3">{passed}/{len(STAGES)} checks passed</span>',
        f'<span class="blue mr2">◉ {counts["running"]} running</span>',
        f'<span class="red mr2">✕ {counts["failed"]} failed</span>',
        f'<span class="navy">↳ {counts["blocked"]} blocked</span></div>',
        '<div class="flex mb2">',
    ]
    for key, label in STAGES.items():
        status = statuses.get(key, 'unknown')
        symbol, text, tint = STATUS[status]
        background = (
            tint if status in {'passed', 'failed', 'running'} else 'silver'
        )
        lines.append(
            f'<span class="flex-auto bg-{background} rounded p1 mr1" '
            f'title="{label}: {text}"></span>'
        )
    lines.append('</div><div class="flex flex-wrap mxn1 mb2">')
    for index, (heading, group) in enumerate(GROUPS.items(), 1):
        group_passed = sum(statuses.get(key) == 'passed' for key in group)
        lines += [
            '<div class="flex-auto border border-silver rounded p2 m1">',
            f'<div class="h6 navy caps mb1">Stage {index:02}</div>',
            f'<div class="h4 bold mb1">{heading}</div>',
            f'<div class="h6 navy mb2">{group_passed}/{len(group)} passed</div>',
        ]
        for key, label in group.items():
            symbol, text, tint = STATUS[statuses.get(key, 'unknown')]
            lines.append(
                f'<div class="mb1"><span class="{tint} bold mr1">{symbol}</span>'
                f'{label}<span class="block h6 navy ml2">{text}</span></div>'
            )
        lines.append('</div>')
    lines.append('</div>')
    if counts['failed']:
        links = ' · '.join(
            f'<a href="artifact://reports/{key}.txt">{STAGES[key]} log ↗</a>'
            for key in STAGES
            if statuses.get(key) == 'failed'
        )
        lines.append(
            f'<div class="border-left border-red pl2 mb2"><b>Investigate:</b> {links}</div>'
        )
    if notice:
        lines.append(f'<div class="orange bold mb2">{escape(notice)}</div>')
    links = []
    for key, path, label in [
        ('iterators', 'reports/coverage-iterators.txt', 'Iterator coverage'),
        ('recipes', 'reports/coverage-recipes.txt', 'Recipe coverage'),
        ('wheel', 'dist/*.whl', 'Wheel ↓'),
        ('sdist', 'dist/*.tar.gz', 'Source ↓'),
        ('metadata', 'reports/checksums.txt', 'Checksums'),
    ]:
        if statuses.get(key) == 'passed':
            links.append(f'<a href="artifact://{path}">{label}</a>')
    if links:
        lines.append(
            '<div class="mb2">' + ' &nbsp; · &nbsp; '.join(links) + '</div>'
        )
    refresh = 'Final snapshot' if done else 'Refreshes about every 3s'
    if notice:
        refresh = 'Updates stopped'
    lines += [
        '<div class="border-top border-silver pt2 h6 navy">',
        f'Python 3.12 · pb-elastic · {refresh} · Updated {escape(updated)}',
        '<div class="mt1">109 selected API tests · Source secret scan · '
        'Packages validated, never published</div></div></div>',
    ]
    return '\n'.join(lines) + '\n', style


def step_for(key):
    result = subprocess.run(
        ['buildkite-agent', 'step', 'get', '--format', 'json', '--step', key],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    step = json.loads(result.stdout)
    return {'state': step['state'], 'outcome': step['outcome']}


def publish(statuses, notice=''):
    updated = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
    markdown, style = render(statuses, updated, notice)
    Path('reports/summary.md').write_text(markdown)
    Path('reports/summary.json').write_text(
        json.dumps(
            {
                'build': os.environ['BUILDKITE_BUILD_URL'],
                'commit': os.environ['BUILDKITE_COMMIT'],
                'updated': updated,
                'notice': notice,
                'checks': statuses,
            },
            indent=2,
        )
        + '\n'
    )
    print(f'{updated} {style}: {json.dumps(statuses)}', flush=True)
    subprocess.run(
        [
            'buildkite-agent',
            'annotate',
            '--context',
            'ci-summary',
            '--style',
            style,
        ],
        input=markdown,
        text=True,
        check=True,
        timeout=20,
    )


def main():
    deadline = time.monotonic() + 540
    statuses = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        try:
            while time.monotonic() < deadline:
                steps = dict(zip(STAGES, pool.map(step_for, STAGES)))
                statuses = statuses_for(steps)
                publish(statuses)
                if complete(statuses):
                    return
                time.sleep(3)
        except (subprocess.SubprocessError, ValueError) as error:
            publish(
                statuses,
                'Status polling failed; consult the build jobs for current results.',
            )
            raise SystemExit(f'Live reporting failed: {error}') from error
    publish(
        statuses,
        'Reporter timed out; consult the build jobs for current results.',
    )
    raise SystemExit('Live reporter exceeded nine minutes')


if __name__ == '__main__':
    main()
