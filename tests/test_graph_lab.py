import copy
import random
import unittest

from annie.graph_lab import run_lab, validate_graph


def graph(edges=None, *, nodes=None, start='A', target='C', directed=True):
    return {'nodes': nodes or ['A', 'B', 'C'],
            'edges': edges if edges is not None else [
                {'source': 'A', 'target': 'C', 'weight': 10},
                {'source': 'A', 'target': 'B', 'weight': 1},
                {'source': 'B', 'target': 'C', 'weight': 1}],
            'start': start, 'target': target, 'directed': directed}


def edge(source, target, weight=1):
    return {'source': source, 'target': target, 'weight': weight}


class GraphLabTests(unittest.TestCase):
    def test_weighted_counterexample_bfs_hops_are_not_minimum_cost(self):
        result = run_lab(graph(), weighted=True)
        self.assertEqual(result['bfs_path'], ['A', 'C'])
        self.assertEqual(result['bfs_cost'], 10)
        self.assertEqual(result['shortest_path'], ['A', 'B', 'C'])
        self.assertEqual(result['shortest_cost'], 2)
        self.assertTrue(result['reachable'])
        self.assertFalse(result['weights_equal'])
        self.assertFalse(result['within_bfs_assumptions'])
        self.assertEqual(result['steps'][-1]['path'], ['A', 'C'])

    def test_unweighted_uses_unit_cost_regardless_of_stored_weights(self):
        result = run_lab(graph())
        self.assertEqual(result['bfs_path'], ['A', 'C'])
        self.assertEqual(result['shortest_path'], ['A', 'C'])
        self.assertEqual(result['bfs_cost'], 1)
        self.assertEqual(result['shortest_cost'], 1)
        self.assertTrue(result['weights_equal'])
        self.assertTrue(result['within_bfs_assumptions'])

    def test_equal_positive_and_zero_weights_satisfy_effective_assumptions(self):
        for weight in (0, 2.5):
            with self.subTest(weight=weight):
                result = run_lab(graph([edge('A', 'B', weight), edge('B', 'C', weight),
                                        edge('A', 'C', weight)]), weighted=True)
                self.assertTrue(result['weights_equal'])
                self.assertTrue(result['within_bfs_assumptions'])
                self.assertEqual(result['bfs_cost'], weight)
                self.assertEqual(result['shortest_cost'], weight)

    def test_disconnected_graph_has_empty_paths_and_null_costs(self):
        result = run_lab(graph([edge('A', 'B')]), weighted=True)
        self.assertFalse(result['reachable'])
        for key in ('bfs_path', 'shortest_path'):
            self.assertEqual(result[key], [])
        for key in ('bfs_cost', 'shortest_cost'):
            self.assertIsNone(result[key])
        self.assertEqual(result['steps'][-1]['path'], [])
        self.assertEqual(result['steps'][-1]['queue'], [])
        self.assertIsNone(result['steps'][-1]['current'])

    def test_empty_graph_edges_are_valid_and_vacuously_equal(self):
        result = run_lab(graph([]), weighted=True)
        self.assertFalse(result['reachable'])
        self.assertTrue(result['weights_equal'])
        self.assertEqual([s['event'] for s in result['steps']], ['start', 'visit', 'finished'])

    def test_start_is_target_is_reached_without_traversal(self):
        result = run_lab(graph(start='B', target='B'), weighted=True)
        self.assertEqual(result['bfs_path'], ['B'])
        self.assertEqual(result['shortest_path'], ['B'])
        self.assertEqual(result['bfs_cost'], 0)
        self.assertEqual(result['shortest_cost'], 0)
        self.assertEqual(result['steps'][-1]['visited'], ['B'])
        self.assertEqual(result['steps'][-1]['queue'], [])

    def test_cycles_and_self_loops_do_not_enqueue_nodes_twice(self):
        g = graph([edge('A', 'A', 0), edge('A', 'B', 0), edge('B', 'A', 0),
                   edge('B', 'B', 0), edge('B', 'C', 1), edge('C', 'A', 0)])
        result = run_lab(g, weighted=True)
        self.assertEqual(result['bfs_path'], ['A', 'B', 'C'])
        self.assertEqual(result['shortest_cost'], 1)
        self.assertEqual(result['steps'][-1]['visited'], ['A', 'B', 'C'])
        self.assertEqual(sum(s['event'] == 'discover' for s in result['steps']), 2)
        self.assertTrue(any(s['event'] == 'skip' and s['edge'] == ['A', 'A']
                            for s in result['steps']))

    def test_directed_and_undirected_edges_have_different_reachability(self):
        g = graph([edge('B', 'A'), edge('C', 'B')])
        self.assertFalse(run_lab(g)['reachable'])
        g['directed'] = False
        result = run_lab(g)
        self.assertEqual(result['bfs_path'], ['A', 'B', 'C'])
        self.assertEqual(result['shortest_cost'], 2)

    def test_bfs_and_shortest_cost_ties_follow_edge_order_not_node_names(self):
        g = graph([edge('A', 'Z'), edge('A', 'B'), edge('Z', 'C'), edge('B', 'C')],
                  nodes=['A', 'B', 'C', 'Z'])
        first = run_lab(g, weighted=True)
        self.assertEqual(first['bfs_path'], ['A', 'Z', 'C'])
        self.assertEqual(first['shortest_path'], ['A', 'Z', 'C'])
        g['edges'][0], g['edges'][1] = g['edges'][1], g['edges'][0]
        second = run_lab(g, weighted=True)
        self.assertEqual(second['bfs_path'], ['A', 'B', 'C'])
        self.assertEqual(second['shortest_path'], ['A', 'B', 'C'])

    def test_assumptions_flag_is_not_a_claim_that_bfs_result_is_wrong(self):
        result = run_lab(graph([edge('A', 'C', 1), edge('A', 'B', 10), edge('B', 'C', 10)]),
                         weighted=True)
        self.assertFalse(result['within_bfs_assumptions'])
        self.assertEqual(result['bfs_path'], result['shortest_path'])
        self.assertEqual(result['bfs_cost'], result['shortest_cost'])

    def test_snapshot_queue_and_discovery_invariants_and_detached_lists(self):
        g = graph([edge('A', 'B'), edge('A', 'C'), edge('B', 'C')])
        before = copy.deepcopy(g)
        result = run_lab(g)
        self.assertEqual(g, before)
        discovered = []
        for step in result['steps']:
            self.assertEqual(set(step), {'event', 'current', 'queue', 'visited', 'path', 'edge'})
            self.assertEqual(len(step['queue']), len(set(step['queue'])))
            self.assertEqual(len(step['visited']), len(set(step['visited'])))
            self.assertTrue(set(step['queue']).issubset(step['visited']))
            self.assertEqual(step['visited'][:len(discovered)], discovered)
            discovered = list(step['visited'])
        frozen_second = copy.deepcopy(result['steps'][1])
        result['steps'][0]['queue'].append('MUTATED')
        result['steps'][0]['visited'].append('MUTATED')
        result['steps'][-1]['path'].append('MUTATED')
        self.assertEqual(result['steps'][1], frozen_second)
        self.assertEqual(result['bfs_path'], ['A', 'C'])
        edges = [s['edge'] for s in result['steps'] if s['edge'] is not None]
        if len(edges) > 1:
            expected = list(edges[1])
            edges[0].append('MUTATED')
            self.assertEqual(edges[1], expected)

    def test_canonical_graph_is_detached_and_preserves_order(self):
        original = graph()
        canonical = validate_graph(original)
        self.assertEqual(canonical['nodes'], original['nodes'])
        self.assertEqual([e['target'] for e in canonical['edges']], ['C', 'B', 'C'])
        canonical['nodes'].append('D')
        canonical['edges'][0]['weight'] = 20
        self.assertEqual(original['nodes'], ['A', 'B', 'C'])
        self.assertEqual(original['edges'][0]['weight'], 10)

    def test_node_bounds_ids_missing_fields_and_wrong_types_raise_valueerror(self):
        invalid = [None, [], {}, {**graph(), 'code': 'print(1)'},
                   graph(nodes=['A']), graph(nodes=[str(i) for i in range(13)]),
                   graph(nodes=['A', 'A', 'C']), graph(nodes=['A', 'B', 'bad node']),
                   graph(nodes=['A', 'B', 'abcdefghijklmn']), graph(nodes=['A', 'B', 'ж']),
                   graph(nodes=['A', 'B', True]), graph(start='X'), graph(target=[]),
                   graph(directed=1), {**graph(), 'nodes': ('A', 'B', 'C')},
                   {**graph(), 'edges': ()}]
        for g in invalid:
            with self.subTest(graph=g), self.assertRaises(ValueError):
                validate_graph(g)
        for weighted in (1, None, 'true'):
            with self.subTest(weighted=weighted), self.assertRaises(ValueError):
                run_lab(graph(), weighted=weighted)

    def test_bad_weights_and_endpoints_raise_valueerror(self):
        for weight in (-1, 101, True, None, '1', float('nan'), float('inf'), -float('inf'), 10 ** 500):
            with self.subTest(weight=weight), self.assertRaises(ValueError):
                validate_graph(graph([edge('A', 'B', weight)]))
        for bad in (edge('A', 'D'), edge(None, 'B'), edge('A', []), {},
                    {'source': 'A', 'target': 'B'}, {**edge('A', 'B'), 'execute': 'anything'}):
            with self.subTest(edge=bad), self.assertRaises(ValueError):
                validate_graph(graph([bad]))

    def test_duplicate_edges_and_undirected_reverse_duplicates_rejected(self):
        for g in (graph([edge('A', 'B'), edge('A', 'B', 2)]),
                  graph([edge('A', 'B'), edge('B', 'A')], directed=False),
                  graph([edge('A', 'A'), edge('A', 'A')], directed=False)):
            with self.subTest(graph=g), self.assertRaises(ValueError):
                validate_graph(g)
        validate_graph(graph([edge('A', 'B'), edge('B', 'A')], directed=True))

    def test_maximum_bounds_and_trace_remain_bounded(self):
        nodes = ['N' + str(i) for i in range(12)]
        edges = [edge(source, target, 100) for source in nodes for target in nodes][:32]
        g = graph(edges, nodes=nodes, start='N0', target='N11')
        canonical = validate_graph(g)
        self.assertEqual(len(canonical['edges']), 32)
        self.assertLessEqual(len(run_lab(g, weighted=True)['steps']), 90)
        g['edges'].append(edge('N11', 'N11'))
        with self.assertRaises(ValueError):
            validate_graph(g)

    def test_fixed_seed_graphs_agree_with_exhaustive_simple_path_oracle(self):
        # Independent small-graph oracle: enumerate all simple paths instead of
        # implementing a second BFS or Dijkstra that could mirror their bugs.
        rng = random.Random(1482)
        nodes = ['A', 'B', 'C', 'D', 'E']
        for case in range(120):
            directed = bool(case % 2)
            pairs = [(source, target) for i, source in enumerate(nodes)
                     for j, target in enumerate(nodes) if directed or i <= j]
            rng.shuffle(pairs)
            edges = [edge(source, target, rng.randrange(6))
                     for source, target in pairs[:rng.randrange(13)]]
            candidate = graph(edges, nodes=nodes, start='A', target='E', directed=directed)
            adjacency = {node: [] for node in nodes}
            for item in edges:
                adjacency[item['source']].append((item['target'], item['weight']))
                if not directed and item['source'] != item['target']:
                    adjacency[item['target']].append((item['source'], item['weight']))
            paths = []

            def enumerate_paths(path, cost):
                if path[-1] == 'E':
                    paths.append((len(path) - 1, cost))
                    return
                for neighbor, weight in adjacency[path[-1]]:
                    if neighbor not in path:
                        enumerate_paths(path + [neighbor], cost + weight)

            enumerate_paths(['A'], 0)
            actual = run_lab(candidate, weighted=True)
            with self.subTest(case=case, directed=directed):
                self.assertEqual(actual['reachable'], bool(paths))
                if paths:
                    self.assertEqual(len(actual['bfs_path']) - 1,
                                     min(hops for hops, _ in paths))
                    self.assertEqual(actual['shortest_cost'], min(cost for _, cost in paths))
                else:
                    self.assertIsNone(actual['bfs_cost'])
                    self.assertIsNone(actual['shortest_cost'])


if __name__ == '__main__':
    unittest.main()
