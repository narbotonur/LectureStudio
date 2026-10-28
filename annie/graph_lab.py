"""Small, deterministic graph experiments without executing generated code.

BFS always minimizes hop count. With weighted=True the displayed BFS path cost
uses the supplied weights and is compared with Dijkstra's shortest-cost path.
The assumptions flag describes equal effective edge weights, not a guarantee
about arbitrary graphs, source material, or a student's conceptual understanding.
"""
from collections import deque
import heapq
import itertools
import math
import re


NODE_ID = re.compile(r'[A-Za-z0-9_]{1,12}\Z')
GRAPH_FIELDS = {'nodes', 'edges', 'start', 'target', 'directed'}
EDGE_FIELDS = {'source', 'target', 'weight'}


def validate_graph(graph):
    """Return a detached canonical graph, or ValueError for invalid input.

    Node IDs are case sensitive. Node and edge input order is preserved, because
    edge order determines BFS discovery order and shortest-path tie breaking.
    Self-loops and cycles are allowed; parallel edges are not. In an undirected
    graph, specifying the same pair in reverse is also a duplicate.
    """
    if not isinstance(graph, dict) or set(graph) != GRAPH_FIELDS:
        raise ValueError('A graph requires nodes, edges, start, target and directed only.')
    nodes = graph['nodes']
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 12:
        raise ValueError('Use between 2 and 12 graph nodes.')
    if any(not isinstance(node, str) or NODE_ID.fullmatch(node) is None for node in nodes):
        raise ValueError('Node IDs must be 1–12 ASCII letters, digits or underscores.')
    if len(set(nodes)) != len(nodes):
        raise ValueError('Graph node IDs must be unique.')
    if not isinstance(graph['directed'], bool):
        raise ValueError('The graph directed flag must be a boolean.')
    for field in ('start', 'target'):
        if not isinstance(graph[field], str) or graph[field] not in nodes:
            raise ValueError(f'The graph {field} must name an existing node.')
    edges = graph['edges']
    if not isinstance(edges, list) or len(edges) > 32:
        raise ValueError('Use at most 32 graph edges.')
    normalized, seen = [], set()
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != EDGE_FIELDS:
            raise ValueError('Each graph edge requires source, target and weight only.')
        source, target, weight = edge['source'], edge['target'], edge['weight']
        if (not isinstance(source, str) or not isinstance(target, str)
                or source not in nodes or target not in nodes):
            raise ValueError('Every edge endpoint must name an existing node.')
        if (isinstance(weight, bool) or not isinstance(weight, (int, float))
                or weight < 0 or weight > 100 or not math.isfinite(weight)):
            raise ValueError('Edge weights must be finite numbers between 0 and 100.')
        identity = (source, target) if graph['directed'] else tuple(sorted((source, target)))
        if identity in seen:
            raise ValueError('Duplicate graph edges are not supported.')
        seen.add(identity)
        normalized.append({'source': source, 'target': target,
                           'weight': 0.0 if weight == 0 else float(weight)})
    return {'nodes': list(nodes), 'edges': normalized, 'start': graph['start'],
            'target': graph['target'], 'directed': graph['directed']}


def _path(parents, start, target):
    if target not in parents:
        return []
    result = [target]
    while result[-1] != start:
        result.append(parents[result[-1]])
    result.reverse()
    return result


def _shortest(adjacency, start, target):
    """Dijkstra with stable insertion-order ties; never reparent on equal cost."""
    order = itertools.count()
    frontier = [(0.0, next(order), start)]
    distances, parents = {start: 0.0}, {start: None}
    settled = set()
    while frontier:
        distance, _, current = heapq.heappop(frontier)
        if current in settled:
            continue
        settled.add(current)
        if current == target:
            return _path(parents, start, target), distance
        for neighbor, weight in adjacency[current]:
            if neighbor in settled:
                continue
            candidate = distance + weight
            if neighbor not in distances or candidate < distances[neighbor]:
                distances[neighbor] = candidate
                parents[neighbor] = current
                heapq.heappush(frontier, (candidate, next(order), neighbor))
    return [], None


def run_lab(graph, weighted=False):
    """Run a bounded BFS trace and shortest-cost comparison.

    visited is the discovery/enqueue order, not the order of completed expansion.
    Events: start, visit (after dequeue), discover (after enqueue), skip (already
    discovered), reached and finished. edge is set on discover/skip events only.
    path remains empty until the target is reached; the final snapshot contains
    the reached BFS path or an empty path when unreachable. Every snapshot owns
    its lists. weighted=False treats all edges as cost 1, including stored zero
    weights. With zero or one edge, effective edge weights are vacuously equal.
    """
    graph = validate_graph(graph)
    if not isinstance(weighted, bool):
        raise ValueError('The weighted flag must be a boolean.')
    adjacency = {node: [] for node in graph['nodes']}
    costs, effective_weights = {}, []
    for edge in graph['edges']:
        source, target = edge['source'], edge['target']
        weight = edge['weight'] if weighted else 1.0
        effective_weights.append(weight)
        adjacency[source].append((target, weight))
        costs[source, target] = weight
        if not graph['directed'] and source != target:
            adjacency[target].append((source, weight))
            costs[target, source] = weight
    start, target = graph['start'], graph['target']
    queue, visited, seen = deque([start]), [start], {start}
    parents, steps, bfs_path = {start: None}, [], []

    def capture(event, current=None, edge=None):
        steps.append({'event': event, 'current': current, 'queue': list(queue),
                      'visited': list(visited), 'path': list(bfs_path),
                      'edge': list(edge) if edge is not None else None})

    capture('start')
    reached = None
    while queue:
        current = queue.popleft()
        capture('visit', current)
        if current == target:
            bfs_path = _path(parents, start, target)
            reached = current
            capture('reached', current)
            break
        for neighbor, _ in adjacency[current]:
            if neighbor in seen:
                capture('skip', current, (current, neighbor))
                continue
            seen.add(neighbor)
            visited.append(neighbor)
            parents[neighbor] = current
            queue.append(neighbor)
            capture('discover', current, (current, neighbor))
    capture('finished', reached)
    bfs_cost = (sum(costs[source, destination] for source, destination in zip(bfs_path, bfs_path[1:]))
                if bfs_path else None)
    shortest_path, shortest_cost = _shortest(adjacency, start, target)
    weights_equal = len(set(effective_weights)) <= 1
    return {'steps': steps, 'bfs_path': list(bfs_path), 'bfs_cost': bfs_cost,
            'shortest_path': shortest_path, 'shortest_cost': shortest_cost,
            'reachable': bool(bfs_path), 'weights_equal': weights_equal,
            'within_bfs_assumptions': weights_equal}
