"""Fictional source -> checked spec -> executed experiment -> persisted attempt.

Default is offline. --live makes one bounded Meta request with authored text.
All saved labs and predictions use a temporary profile, never personal material.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = 'Authored BFS demonstration'
SEGMENTS = [
    {'start': 0, 'end': 12, 'source': SOURCE,
     'text': 'Breadth-first search, or BFS, finds a path with the fewest edges in an unweighted graph.'},
    {'start': 12, 'end': 22, 'source': SOURCE,
     'text': 'We assume each edge has equal cost. Use a queue and mark vertices when you enqueue them.'}]
EXPERIMENT = {'nodes': ['A', 'B', 'C'], 'directed': True, 'start': 'A', 'target': 'C',
    'edges': [{'source': 'A', 'target': 'C', 'weight': 10},
              {'source': 'A', 'target': 'B', 'weight': 1},
              {'source': 'B', 'target': 'C', 'weight': 1}]}


def fixture_response(*_):
    return json.dumps({'supported': True, 'title': 'BFS: hops and weighted cost',
        'reason': 'The source discusses BFS and its equal-edge assumption.',
        'claim': 'BFS finds a path with the fewest edges in an unweighted graph.',
        'assumptions': ['The lecture assumes equal edge costs.'],
        'graph_origin': 'constructed_example', 'graph': EXPERIMENT,
        'evidence': [{'quote': s['text'], 't_start': s['start'], 't_end': s['end'],
                      'source': s['source']} for s in SEGMENTS]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    from annie.executable_lectures import generate_lab, LabStore
    from annie.graph_lab import run_lab
    started = time.monotonic()
    spec = generate_lab(SEGMENTS, 'CSCI 231', SOURCE,
                        generator=None if args.live else fixture_response)
    unweighted = run_lab(spec['graph'])
    # This edited graph is an authored experimental variant, not teacher data
    # and not a claim that the model generated these particular numbers.
    counterexample = run_lab(EXPERIMENT, weighted=True)
    assert counterexample['bfs_path'] == ['A', 'C']
    assert counterexample['bfs_cost'] == 10 and counterexample['shortest_cost'] == 2
    assert not counterexample['within_bfs_assumptions']
    with tempfile.TemporaryDirectory(prefix='executable-lecture-check-') as root:
        store = LabStore(root)
        identity = store.save(spec)
        wrong = store.record_attempt(identity, graph=EXPERIMENT, weighted=True, predicted_cost=2)
        right = store.record_attempt(identity, graph=EXPERIMENT, weighted=True, predicted_cost=10)
        assert wrong['correct'] is False and right['correct'] is True
        assert len(LabStore(root).attempts(identity)) == 2
        assert LabStore(root).get(identity)['fingerprint'] == spec['fingerprint']
    report = {'mode': 'one live Meta request' if args.live else 'supplied offline fixture',
        'passed': True, 'personal_data_used': False, 'source_quotes': len(spec['evidence']),
        'generated_graph_origin': spec['graph_origin'],
        'generated_graph_nodes': len(spec['graph']['nodes']),
        'generated_graph_reachable': unweighted['reachable'],
        'experimental_variant': 'authored A-C10 A-B1 B-C1, separate from source facts',
        'bfs_route_cost': 10, 'shortest_route_cost': 2,
        'wrong_prediction_rejected': True, 'correct_prediction_saved': True,
        'attempts_survive_reopening': True,
        'model_metadata': spec.get('model_metadata'),
        'elapsed_seconds': round(time.monotonic() - started, 3)}
    output = ROOT / 'review_artifacts' / 'executable-lecture'
    output.mkdir(parents=True, exist_ok=True)
    prefix = 'live' if args.live else 'offline'
    (output / (prefix + '.json')).write_text(json.dumps(report, indent=2), encoding='utf-8')
    (output / (prefix + '-spec.json')).write_text(json.dumps(spec, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
