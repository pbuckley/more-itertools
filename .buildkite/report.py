import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess


STAGES = {
    'prepare': 'Prepare source & tools',
    'lint': 'Lint',
    'format': 'Formatting',
    'types': 'Type-stub contracts',
    'secrets': 'Source secret scan',
    'iterators': 'Iterator tests',
    'recipes': 'Recipe tests',
    'wheel': 'Build wheel',
    'sdist': 'Build source distribution',
    'install': 'Installed-wheel smoke test',
    'metadata': 'Metadata & checksums',
}


def render(states):
    passed = sum(state == 'passed' for state in states.values())
    success = all(states.get(key) == 'passed' for key in STAGES)
    title = (
        'Release candidate verified'
        if success
        else 'Release candidate incomplete'
    )
    lines = [
        f'## {title}',
        '',
        f'**{passed}/{len(STAGES)} checks passed.**',
        '',
    ]
    lines += ['| Check | Result |', '| --- | --- |']
    for key, label in STAGES.items():
        state = states.get(key, 'unknown')
        lines.append(f'| {label} | {state} |')
    lines += [
        '',
        'Reports and distributions are in this build’s **Artifacts** tab.',
        'This pipeline validates packages; it does not publish a release.',
    ]
    return '\n'.join(lines) + '\n', 'success' if success else 'error'


def outcome_for(key):
    result = subprocess.run(
        ['buildkite-agent', 'step', 'get', 'outcome', '--step', key],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        states = dict(zip(STAGES, pool.map(outcome_for, STAGES)))
    markdown, style = render(states)
    Path('reports/summary.md').write_text(markdown)
    Path('reports/summary.json').write_text(
        json.dumps(
            {
                'build': os.environ['BUILDKITE_BUILD_URL'],
                'commit': os.environ['BUILDKITE_COMMIT'],
                'checks': states,
            },
            indent=2,
        )
        + '\n'
    )
    print(markdown)
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
    )


if __name__ == '__main__':
    main()
