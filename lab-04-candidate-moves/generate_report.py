"""Generate the Lab 04 report (candidate moves) as a PDF.

The report is built as HTML with explicit A4 pages and printed to PDF by a headless
Chromium-based browser (Microsoft Edge or Google Chrome). Inputs are the files written by the
lab04 executable:

    build/lab04.exe --seed 20260404                       -> main experiment
    build/lab04.exe --seed 20260404 --ranking-experiment  -> definitions of "nearest"

Usage: python generate_report.py [--html-only]
The browser can be chosen with the REPORT_BROWSER environment variable.
"""

from __future__ import annotations

import csv
import html
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVALUATION = ROOT / "evaluation"
DATA_DIR = ROOT.parent / "problem-description" / "data"
CHECKER = DATA_DIR / "Solution checker.xlsx"
BUILD = ROOT / ".report-build"
REPORT_HTML = BUILD / "report.html"
REPORT_PDF = ROOT / "report.pdf"

AUTHORS = (("Paweł Świątek", "160301"), ("Jędrzej Szmidt", "160292"))
REPOSITORY_URL = "https://github.com/Flat-Earther/Evolutionary-Computation/tree/main/lab-04-candidate-moves"
INSTANCES = ("TSPA", "TSPB")
K_VALUES = (1, 5, 10, 15, 20, 30, 50)
METHODS = ("steepest_2opt",) + tuple(f"candidate_k{k}" for k in K_VALUES)
METRICS = ("distance", "cost", "distance_plus_cost")
METRIC_LABEL = {"distance": "distance", "cost": "cost", "distance_plus_cost": "distance + cost"}
METRIC_FORMULA = {"distance": "d(u, v)", "cost": "c(v)", "distance_plus_cost": "d(u, v) + c(v)"}
DEFAULT_DEFINITION = ("distance", "distance_plus_cost")  # (intra, inter) used in the main experiment
FULL_KEY = ("none", "none", 0)

# Sequential blue ramp (documented steps 250/350/450/550/650, validated as an ordinal ramp):
# node cost, light = cheap, dark = expensive.
NODE_RAMP = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281")
# Table shading uses the light steps 100/200/300 of the same ramp (classes s1, s2, s3).
SCORE_BUCKETS = (0.0, 0.0025, 0.01)  # relative gap to the best average: best, <= 0.25 %, <= 1 %
TIME_BUCKETS = (0.5, 0.75, 1.0)      # ratio to the full neighbourhood: <= 0.5x, <= 0.75x, < 1x (faster)


# ----------------------------------------------------------------------------------- data

def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        sys.exit(f"missing {path} - run the lab04 experiments first (see the README)")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def grid_key(row: dict[str, str]) -> tuple[str, str, int]:
    return row["intra"], row["inter"], int(row["candidate_count"])


class Data:
    def __init__(self) -> None:
        self.stats = {i: {r["method_name"]: r for r in read_csv(EVALUATION / f"{i}_stats.csv")} for i in INSTANCES}
        self.times = {i: {r["method_name"]: r for r in read_csv(EVALUATION / f"{i}_times.csv")} for i in INSTANCES}
        self.grid_stats = {i: {grid_key(r): r for r in read_csv(EVALUATION / f"{i}_ranking_stats.csv")}
                           for i in INSTANCES}
        self.grid_times = {i: {grid_key(r): r for r in read_csv(EVALUATION / f"{i}_ranking_times.csv")}
                           for i in INSTANCES}
        self.grid_best = {i: {grid_key(r): r for r in read_csv(EVALUATION / f"{i}_ranking_best.csv")}
                          for i in INSTANCES}
        self.nodes = {i: load_nodes(i) for i in INSTANCES}
        self.checker = load_checker_tables()

    # Convenience accessors (floats).
    def avg(self, inst: str, method: str) -> float:
        return float(self.stats[inst][method]["avg"])

    def run_ms(self, inst: str, method: str) -> float:
        return float(self.times[inst][method]["average_ms"])

    def list_ms(self, inst: str, method: str) -> float:
        return float(self.times[inst][method]["candidate_list_ms"])

    def grid_avg(self, inst: str, key: tuple[str, str, int]) -> float:
        return float(self.grid_stats[inst][key]["avg"])

    def grid_run_ms(self, inst: str, key: tuple[str, str, int]) -> float:
        return float(self.grid_times[inst][key]["average_ms"])

    def grid_list_ms(self, inst: str, key: tuple[str, str, int]) -> float:
        return float(self.grid_times[inst][key]["candidate_list_ms"])


def load_nodes(instance: str) -> list[tuple[int, int, int]]:
    nodes = []
    for line in (DATA_DIR / "example" / f"{instance}.csv").read_text(encoding="utf-8").splitlines():
        parts = line.replace(",", ";").split(";")
        if len(parts) >= 3 and parts[0].strip():
            nodes.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return nodes


def read_route(instance: str, method_id: str) -> list[int]:
    path = EVALUATION / "results" / f"{instance}_{method_id}.csv"
    route = [int(token) for token in path.read_text(encoding="utf-8").split()]
    return route[:-1] if len(route) > 1 and route[0] == route[-1] else route


def load_checker_tables() -> dict[str, dict[int, tuple[float, float, float]]]:
    """Node table (id -> x, y, cost) of every sheet of the provided solution checker workbook,
    read from its cells A3:D202."""
    main_ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    tables = {}
    with zipfile.ZipFile(CHECKER) as book:
        workbook = ET.fromstring(book.read("xl/workbook.xml"))
        targets = {rel.get("Id"): rel.get("Target") for rel in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
        for sheet in workbook.iter(f"{main_ns}sheet"):
            target = targets[sheet.get(f"{rel_ns}id")].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            values: dict[str, float] = {}
            for cell in ET.fromstring(book.read(target)).iter(f"{main_ns}c"):
                value = cell.find(f"{main_ns}v")
                if value is not None and cell.get("t") is None:
                    values[cell.get("r")] = float(value.text)
            tables[sheet.get("name")] = {int(values[f"A{row}"]): (values[f"B{row}"], values[f"C{row}"], values[f"D{row}"])
                                         for row in range(3, 203) if f"A{row}" in values}
    return tables


def checker_objective(table: dict[int, tuple[float, float, float]], route: list[int]) -> int | None:
    """The checker sheet's computation: node costs + INT(SQRT(dx^2 + dy^2) + 0.5) for every edge of
    the closed list of 100 nodes. None if the list is not a valid solution."""
    if len(route) != 100 or len(set(route)) != 100 or any(node not in table for node in route):
        return None
    total = 0
    for index, node in enumerate(route):
        x, y, cost = table[node]
        nx, ny, _ = table[route[(index + 1) % len(route)]]
        total += int(cost) + int(math.sqrt((x - nx) ** 2 + (y - ny) ** 2) + 0.5)
    return total


# ----------------------------------------------------------------------------- formatting

def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def score_parts(row: dict[str, str]) -> tuple[str, str]:
    return f"{float(row['avg']):.2f}", f"({float(row['min']):.0f} – {float(row['max']):.0f})"


def ms(value: float | str) -> str:
    return f"{float(value):.3f}"


def pct(value: float, reference: float) -> float:
    return 100.0 * (value / reference - 1.0)


def signed_pct(value: float, reference: float) -> str:
    return f"{pct(value, reference):+.2f} %".replace("-", "−")


def method_label(method_id: str) -> str:
    return "Full neighbourhood (baseline)" if method_id == "steepest_2opt" else \
        f"Candidate moves, K = {method_id.removeprefix('candidate_k')}"


def definition_label(intra: str, inter: str) -> str:
    return f"intra: {METRIC_LABEL[intra]}, inter: {METRIC_LABEL[inter]}"


def key_label(key: tuple[str, str, int]) -> str:
    return "full neighbourhood" if key == FULL_KEY else f"K = {key[2]}, {definition_label(key[0], key[1])}"


def shade_class(value: float, best: float, buckets: tuple[float, ...], relative: bool) -> str:
    measure = (value - best) / best if relative else value / best
    if measure <= buckets[0] + 1e-12:
        return "s3"
    if measure <= buckets[1]:
        return "s2"
    if measure <= buckets[2]:
        return "s1"
    return ""


def time_shade_class(value: float, full: float) -> str:
    ratio = value / full
    if ratio <= TIME_BUCKETS[0]:
        return "s3"
    if ratio <= TIME_BUCKETS[1]:
        return "s2"
    if ratio < TIME_BUCKETS[2]:
        return "s1"
    return ""


def k_set(values: list[int]) -> str:
    return f"K = {values[0]}" if len(values) == 1 else "K ∈ {" + ", ".join(str(k) for k in values) + "}"


# ------------------------------------------------------------------------------- figures

def cost_style(cost: int, cmin: int, cmax: int) -> tuple[str, float]:
    t = (cost - cmin) / (cmax - cmin) if cmax > cmin else 0.0
    return NODE_RAMP[min(len(NODE_RAMP) - 1, int(t * len(NODE_RAMP)))], 2.6 + 3.4 * math.sqrt(t)


def solution_svg(nodes: list[tuple[int, int, int]], route: list[int], title: str) -> str:
    width, pad = 400.0, 9.0
    xs, ys, costs = [n[0] for n in nodes], [n[1] for n in nodes], [n[2] for n in nodes]
    scale = (width - 2 * pad) / max(1, max(xs) - min(xs))
    height = (max(ys) - min(ys)) * scale + 2 * pad
    cmin, cmax = min(costs), max(costs)

    def point(node: int) -> tuple[float, float]:
        return pad + (nodes[node][0] - min(xs)) * scale, height - pad - (nodes[node][1] - min(ys)) * scale

    selected = set(route)
    parts = [f'<svg class="plot" viewBox="0 0 {width:.0f} {height:.1f}" role="img" aria-label="{esc(title)}">',
             f'<rect x="0.5" y="0.5" width="{width - 1:.1f}" height="{height - 1:.1f}" rx="3" fill="#fcfcfb" '
             f'stroke="#e1e0d9"/>']
    for node in range(len(nodes)):
        if node not in selected:
            color, radius = cost_style(nodes[node][2], cmin, cmax)
            x, y = point(node)
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.2f}" fill="#fcfcfb" stroke="{color}" '
                         f'stroke-width="0.8"/>')
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in (point(node) for node in route + route[:1]))
    parts.append(f'<polyline points="{points}" fill="none" stroke="#52514e" stroke-width="1.1" stroke-linejoin="round"/>')
    for node in route:
        color, radius = cost_style(nodes[node][2], cmin, cmax)
        x, y = point(node)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.2f}" fill="{color}" stroke="#fcfcfb" '
                     f'stroke-width="0.6"/>')
    parts.append("</svg>")
    return "".join(parts)


def cost_legend(nodes: list[tuple[int, int, int]]) -> str:
    costs = [n[2] for n in nodes]
    cmin, cmax = min(costs), max(costs)
    step = (cmax - cmin) / len(NODE_RAMP)
    # bucket b holds the costs c with b <= 5 (c - cmin) / (cmax - cmin) < b + 1 (the last one includes cmax)
    bounds = [math.ceil(cmin + index * step) for index in range(len(NODE_RAMP))] + [cmax + 1]
    items = []
    for index, color in enumerate(NODE_RAMP):
        _, radius = cost_style(round(cmin + (index + 0.5) * step), cmin, cmax)
        items.append(f'<span class="key"><svg width="14" height="14" viewBox="0 0 14 14"><circle cx="7" cy="7" '
                     f'r="{radius * 0.85:.2f}" fill="{color}"/></svg>{bounds[index]}–{bounds[index + 1] - 1}</span>')
    return ('<div class="legend"><span>Node cost (colour and size):</span>' + "".join(items) +
            '<span class="key"><svg width="14" height="14" viewBox="0 0 14 14"><circle cx="7" cy="7" r="3.6" '
            'fill="#fcfcfb" stroke="#2a78d6" stroke-width="0.9"/></svg>not selected</span>'
            '<span class="key"><svg width="18" height="12" viewBox="0 0 18 12"><line x1="1" y1="6" x2="17" y2="6" '
            'stroke="#52514e" stroke-width="1.2"/></svg>cycle</span></div>')


# --------------------------------------------------------------------------------- pages

class Report:
    def __init__(self) -> None:
        self.pages: list[str] = []

    def page(self, body: str, wide: bool = False) -> None:
        number = len(self.pages) + 1
        footer = (f'<div class="footer"><span>Evolutionary Computation · Assignment 4 · Candidate moves</span>'
                  f'<span>{esc(AUTHORS[0][0])}, {esc(AUTHORS[1][0])} · page {number}</span></div>')
        self.pages.append(f'<section class="page{" wide" if wide else ""}" id="page-{number}">'
                          f'<div class="content">{body}</div>{footer}</section>')


def first_page(report: Report) -> None:
    authors = " &nbsp;·&nbsp; ".join(f"{esc(name)} ({esc(index)})" for name, index in AUTHORS)
    report.page(f"""
<div class="title">
  <div class="kicker">Evolutionary Computation · Assignment 4 · Report</div>
  <h1>The use of candidate moves in local search</h1>
  <div class="meta">{authors}<br>Poznań University of Technology, Artificial Intelligence · November 2026<br>
  Source code: <a href="{REPOSITORY_URL}">{esc(REPOSITORY_URL)}</a></div>
</div>
<h2>1. Problem description</h2>
<p>Every node has integer coordinates (x, y) and an integer cost. The task is to select exactly
<b>m = ⌈n / 2⌉</b> nodes and to arrange them in a Hamiltonian cycle so that the <b>length of the cycle plus the
total cost of the selected nodes</b> is minimal:</p>
<p class="formula">f(S) = Σ<sub>i</sub> d(S[i], S[i+1]) + Σ<sub>i</sub> c(S[i]), &nbsp;&nbsp; S[m] = S[0]</p>
<p>Distances are Euclidean distances rounded mathematically to integers,
d(u, v) = round(√((x<sub>u</sub> − x<sub>v</sub>)² + (y<sub>u</sub> − y<sub>v</sub>)²)). The distance matrix is
computed once after reading an instance; the optimisation methods access only the distance matrix and the node
costs, never the coordinates. Both instances (TSPA, TSPB) have n = 200 nodes, so every solution selects m = 100
nodes. A solution is a list of m distinct node indices (0-based); the closing edge back to the first node is part
of the objective.</p>
<h2>2. Task and methods</h2>
<p>The goal is to make the steepest local search faster with <b>candidate moves</b>, in the neighbourhood that was
the best in the previous assignment: <b>2-opt</b> (two-edges exchange) as the intra-route move and the exchange of a
selected and a not selected node as the inter-route move. A move is a candidate move when it introduces at least
one <b>candidate edge</b> into the solution; candidate edges connect every node with its K "nearest" nodes. Only
candidate moves are generated and evaluated — the full neighbourhood is never enumerated and filtered. Starting
solutions are random. The compared methods are:</p>
<ul>
<li><b>Full neighbourhood (baseline)</b> — the steepest local search of the previous assignment, evaluating every
2-opt move and every exchange.</li>
<li><b>Candidate moves, K = 1, 5, 10, 15, 20, 30, 50</b> — the same steepest local search restricted to candidate
moves, with "nearest" as proposed in the assignment: by the edge length for intra-route (2-opt) candidates and by the
edge length plus the node cost for inter-route candidates.</li>
<li><b>Definitions of "nearest" (additional experiment)</b> — distance, cost, or distance + cost, chosen separately
for intra- and inter-route candidate edges (9 combinations), each for every K.</li>
</ul>
<p>The report contains the pseudocode of all methods (Section 3), the experimental setup (Section 4), the results
(Sections 5 and 6), the best solutions with their visualisation and node lists (Section 7) and the conclusions
(Section 8).</p>""")


PSEUDOCODE_1 = """<span class="c">Notation</span>
  n nodes, m = ⌈n/2⌉ selected; d(u, v) distance matrix; c(v) node cost
  S[0..m-1]  cycle of the selected nodes, indices modulo m; succ(u), pred(u) neighbours of u in S

<b>RANDOM-START</b>()
  P <- random permutation of {0, ..., n-1}           <span class="c">// std::shuffle, mt19937, fixed seed</span>
  return S = (P[0], ..., P[m-1])

<b>STEEPEST-LOCAL-SEARCH</b>(S, NEIGHBOURHOOD)
  repeat
    (move, Δ) <- the move of NEIGHBOURHOOD(S) with the lowest Δ
                 <span class="c">// ties: the first move in a fixed scan order, so every run is reproducible</span>
    if Δ >= 0: return S                              <span class="c">// local optimum</span>
    apply move to S                                  <span class="c">// f(S) <- f(S) + Δ</span>

<span class="c">Moves: only the change Δ of f is computed, a neighbour solution is never built</span>
  <b>2-OPT</b>(i, j), 0 <= i < j <= m-1, (i, j) ≠ (0, m-1): reverse S[i..j]
      a = S[i-1], b = S[i], x = S[j], y = S[j+1]
      Δ = d(a, x) + d(b, y) - d(a, b) - d(x, y)
      <span class="c">// removes (a, b), (x, y), adds (a, x), (b, y); j = i+1 swaps two neighbouring nodes</span>
  <b>EXCHANGE</b>(p, v), v not selected: S[p] <- v
      a = S[p-1], b = S[p+1]
      Δ = d(a, v) + d(v, b) + c(v) - d(a, S[p]) - d(S[p], b) - c(S[p])

<b>FULL-NEIGHBOURHOOD</b>(S)                                  <span class="c">// baseline</span>
  return every 2-OPT(i, j) and every EXCHANGE(p, v)     <span class="c">// m(m-1)/2 - 1 + m(n-m) moves</span>"""

PSEUDOCODE_2 = """<b>BUILD-CANDIDATE-LISTS</b>(K, μ<sub>intra</sub>, μ<sub>inter</sub>)      <span class="c">// once per instance and configuration</span>
  score<sub>distance</sub>(u, v) = d(u, v)
  score<sub>cost</sub>(u, v) = c(v)                          <span class="c">// c(u) would add the same to every v</span>
  score<sub>distance+cost</sub>(u, v) = d(u, v) + c(v)
  for kind in {intra, inter}:
    L<sub>kind</sub>(u) <- ∅ for every node u
    for each node u:
      N <- the K nodes v ≠ u with the lowest score<sub>μ_kind</sub>(u, v)       <span class="c">// ties: smaller index</span>
      for v in N: add v to L<sub>kind</sub>(u) and u to L<sub>kind</sub>(v)            <span class="c">// candidate edge {u, v}</span>

<b>CANDIDATE-NEIGHBOURHOOD</b>(S)           <span class="c">// moves introducing at least one candidate edge</span>
  M <- ∅
  for each selected node u:
    for each selected v in L<sub>intra</sub>(u) that is not a neighbour of u in S:
      <span class="c">// the two 2-opt moves that introduce the candidate edge (u, v)</span>
      add the 2-OPT removing (u, succ u), (v, succ v), adding (u, v), (succ u, succ v)
      add the 2-OPT removing (pred u, u), (pred v, v), adding (u, v), (pred u, pred v)
    for each not selected v in L<sub>inter</sub>(u):
      <span class="c">// the two exchanges that introduce the candidate edge (u, v)</span>
      add EXCHANGE(pos(succ u), v)          <span class="c">// adds (u, v) and (v, succ succ u)</span>
      add EXCHANGE(pos(pred u), v)          <span class="c">// adds (pred pred u, v) and (v, u)</span>
  return M

<b>CANDIDATE-LOCAL-SEARCH</b>(S, K, μ<sub>intra</sub>, μ<sub>inter</sub>)
  BUILD-CANDIDATE-LISTS(K, μ<sub>intra</sub>, μ<sub>inter</sub>)                <span class="c">// timed separately</span>
  return STEEPEST-LOCAL-SEARCH(S, CANDIDATE-NEIGHBOURHOOD)"""


def algorithm_pages(report: Report) -> None:
    report.page(f"""
<h2>3. Algorithms (pseudocode)</h2>
<p>Both methods use the same steepest local search; they differ only in the neighbourhood searched in every
iteration.</p>
<pre class="code">{PSEUDOCODE_1}</pre>
<pre class="code">{PSEUDOCODE_2}</pre>""")
    report.page("""
<h2>3.1 Implementation</h2>
<p>The neighbourhoods above define which moves are evaluated. The implementation (C++17) evaluates exactly these
moves and applies the same move in every iteration as a straightforward implementation that first builds the list
of all moves — this was verified run by run, with identical local optima, on both instances for every
configuration. It is organised for speed:</p>
<ul>
<li><b>Deltas only.</b> No neighbour solution is built and the objective is never recomputed during the search. The
route is stored with sentinel copies of its ends (no modulo arithmetic); the lengths of the route edges and the
positions of the nodes are cached and updated after every applied move. After every run the objective is recomputed
from scratch and checked against the accumulated deltas.</li>
<li><b>Full neighbourhood.</b> All moves are evaluated, row by row: the 2-opt moves with a fixed first position and
the exchanges at one position. Each row is reduced to its minimum without branches (the exchange row runs over all
nodes, selected nodes receive a large penalty, so the compiler vectorises it); the position of the minimum is looked
up only when the row beats the best move found so far.</li>
<li><b>Candidate lists</b> are symmetric (an edge chosen by either endpoint is in both lists) and stored in compact
arrays together with the parts of the deltas that do not change: d(u, v) for 2-opt, d(u, v) + c(v) for
exchanges. The K nearest nodes are selected with a linear-time selection, not a full sort.</li>
<li><b>Only useful candidates are visited.</b> For every list, a bit mask marks the candidates that are currently
selected (2-opt) or not selected (exchanges); it is updated when a node enters or leaves the solution. A pair of
selected nodes is evaluated once, from the endpoint that comes first in the route.</li>
<li><b>Exact pruning of exchanges.</b> Exchange lists are sorted by d(u, v) + c(v). An exchange adds at least this
amount, so the scan of a list stops at the first candidate that can no longer match the best move found so far.
This skips most exchange candidates without changing the result.</li>
<li><b>Ties.</b> Every move carries its position in the scan order of the straightforward implementation, and among
moves with equal Δ the earliest one is applied. Equal deltas are common with integer distances; this makes the result
independent of the order in which the moves are actually visited.</li>
</ul>
<h2>4. Computational experiment</h2>
<ul>
<li><b>Runs.</b> Every method was run 200 times on each instance, always from the same 200 random starting solutions
(seed 20260404 combined with an instance-specific constant). Every run continues until no improving move exists.</li>
<li><b>Configurations.</b> Main experiment (Section 5): the full neighbourhood and candidate moves with
K ∈ {1, 5, 10, 15, 20, 30, 50} and the proposed definition of "nearest". Additional experiment (Section 6): 3 × 3
definitions of "nearest" × 7 values of K = 63 configurations per instance, plus the full neighbourhood.</li>
<li><b>Running times</b> are wall-clock times of one local-search run, from the starting solution to the local
optimum. Building the candidate lists is not part of a run: the lists depend only on the instance, K and the
definition of "nearest", so they are built once. Their construction time was measured separately (median of 25
constructions); "with lists" is the time a run would take if the nearest nodes had to be computed at its beginning.
The runs of all methods of an experiment were interleaved (for every starting solution, every method once), so
changes of the processor clock affect all methods alike. Times from the two experiments come from separate
sessions and can differ slightly for the same configuration. Single maxima can be inflated by interruptions from the
operating system; the averages and minima are the more reliable figures.</li>
<li><b>Environment.</b> AMD Ryzen 7 7840HS, Windows 11; GCC 16.2 (MSYS2 UCRT64), CMake Release build
(<span class="nowrap">-O3 -march=x86-64-v2</span>), single thread.</li>
</ul>""")


def main_results_page(report: Report, data: Data, observations: str) -> None:
    best_avg = {i: min(data.avg(i, m) for m in METHODS) for i in INSTANCES}
    best_time = {i: min(data.run_ms(i, m) for m in METHODS) for i in INSTANCES}
    score_rows, time_rows = [], []
    for method in METHODS:
        cells = []
        for inst in INSTANCES:
            avg, spread = score_parts(data.stats[inst][method])
            cls = ' class="best"' if data.avg(inst, method) == best_avg[inst] else ""
            cells.append(f"<td{cls}>{avg} {spread}</td>")
        score_rows.append(f"<tr><th>{esc(method_label(method))}</th>{''.join(cells)}</tr>")
        cells = []
        for inst in INSTANCES:
            row = data.times[inst][method]
            cls = ' class="best"' if data.run_ms(inst, method) == best_time[inst] else ""
            if method == "steepest_2opt":
                with_lists = "— <span class=\"sub\">(no lists)</span>"
            else:
                lists = data.list_ms(inst, method)
                with_lists = f"{ms(data.run_ms(inst, method) + lists)} <span class=\"sub\">(lists {ms(lists)})</span>"
            cells.append(f"<td{cls}>{ms(row['average_ms'])} ({ms(row['minimum_ms'])} – {ms(row['maximum_ms'])})</td>"
                         f"<td>{with_lists}</td>")
        time_rows.append(f"<tr><th>{esc(method_label(method))}</th>{''.join(cells)}</tr>")
    report.page(f"""
<h2>5. Results — candidate moves vs. the full neighbourhood</h2>
<p>"Nearest" as proposed in the assignment: edge length for 2-opt candidates, edge length + node cost for exchange
candidates. 200 runs per method and instance; the lowest average in every column is in bold.</p>
<table class="results">
<caption>Table 1. Objective function: average (minimum – maximum)</caption>
<thead><tr><th>Method</th><th>TSPA</th><th>TSPB</th></tr></thead>
<tbody>{''.join(score_rows)}</tbody></table>
<table class="results times">
<caption>Table 2. Running time of one local-search run in ms: average (minimum – maximum); "with lists" adds the
construction of the candidate lists to the average</caption>
<thead><tr><th rowspan="2">Method</th><th colspan="2">TSPA</th><th colspan="2">TSPB</th></tr>
<tr><th>local search</th><th>with lists</th><th>local search</th><th>with lists</th></tr></thead>
<tbody>{''.join(time_rows)}</tbody></table>
{observations}""")


def grid_table(data: Data, inst: str, kind: str) -> str:
    keys = [(intra, inter, k) for intra in METRICS for inter in METRICS for k in K_VALUES]
    values = {key: data.grid_avg(inst, key) if kind == "score" else data.grid_run_ms(inst, key) for key in keys}
    best = min(values.values())
    head = "".join(f"<th>K = {k}</th>" for k in K_VALUES)
    rows = []
    for intra in METRICS:
        for index, inter in enumerate(METRICS):
            cells = []
            for k in K_VALUES:
                key = (intra, inter, k)
                if kind == "score":
                    avg, spread = score_parts(data.grid_stats[inst][key])
                    shade = shade_class(values[key], best, SCORE_BUCKETS, True)
                    content = f'<span class="main">{avg}</span><span class="sub">{spread}</span>'
                else:
                    row = data.grid_times[inst][key]
                    shade = time_shade_class(values[key], data.grid_run_ms(inst, FULL_KEY))
                    content = (f'<span class="main">{ms(row["average_ms"])}</span>'
                               f'<span class="sub">({ms(row["minimum_ms"])} – {ms(row["maximum_ms"])})</span>'
                               f'<span class="sub">with lists {ms(data.grid_run_ms(inst, key) + data.grid_list_ms(inst, key))}'
                               f'</span>')
                cell_class = f' class="{shade}"' if shade else ""
                cells.append(f"<td{cell_class}>{content}</td>")
            star = " ★" if (intra, inter) == DEFAULT_DEFINITION else ""
            intra_cell = (f'<th rowspan="3" class="group">{esc(METRIC_LABEL[intra])}<span class="sub">'
                          f'{esc(METRIC_FORMULA[intra])}</span></th>' if index == 0 else "")
            row_class = ' class="first"' if index == 0 else ""
            rows.append(f'<tr{row_class}>{intra_cell}'
                        f'<th>{esc(METRIC_LABEL[inter])}{star}<span class="sub">{esc(METRIC_FORMULA[inter])}</span></th>'
                        f'{"".join(cells)}</tr>')
    return (f'<table class="grid {kind}"><thead><tr><th>intra (2-opt)</th><th>inter (exchange)</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def grid_pages(report: Report, data: Data, notes: dict[tuple[str, str], str]) -> None:
    number = 3
    for inst in INSTANCES:
        full_stats, full_times = data.grid_stats[inst][FULL_KEY], data.grid_times[inst][FULL_KEY]
        avg, spread = score_parts(full_stats)
        for kind in ("score", "time"):
            if kind == "score":
                title = f"Table {number}. {inst} — objective function: average (minimum – maximum)"
                baseline = f"Full neighbourhood (no candidate lists, same session): <b>{avg}</b> {spread}."
                legend = ('Shading — distance to the best average in the table: <span class="chip s3">best</span>'
                          '<span class="chip s2">≤ 0.25 %</span><span class="chip s1">≤ 1 %</span>; larger gaps are '
                          'not shaded.')
            else:
                title = (f"Table {number}. {inst} — running time of one local-search run in ms: average (minimum – "
                         f"maximum); \"with lists\" adds the construction of the candidate lists")
                baseline = (f"Full neighbourhood (no candidate lists, same session): <b>{ms(full_times['average_ms'])}"
                            f"</b> ({ms(full_times['minimum_ms'])} – {ms(full_times['maximum_ms'])}) ms.")
                legend = ('Shading — average run time relative to the full neighbourhood: '
                          '<span class="chip s3">≤ 0.5×</span><span class="chip s2">≤ 0.75×</span>'
                          '<span class="chip s1">&lt; 1×</span>; configurations slower than the full neighbourhood are '
                          'not shaded.')
            intro = ("<h2>6. Definitions of \"nearest\" nodes</h2><p>The candidate edges of 2-opt moves (intra) and of "
                     "exchanges (inter) are chosen independently, by distance d(u, v), cost c(v), or distance + cost "
                     "d(u, v) + c(v); ★ marks the definition proposed in the assignment (used in Section 5). The 63 "
                     "configurations and the full neighbourhood were run in one interleaved session per instance, 200 "
                     "runs each.</p>" if number == 3 else "")
            report.page(f'{intro}<div class="tablehead">{title}</div>{grid_table(data, inst, kind)}'
                        f'<p class="note">{baseline} {legend}</p><p class="note">{notes[(inst, kind)]}</p>', wide=True)
            number += 1


def best_solution_pages(report: Report, data: Data) -> list[str]:
    """Cards with the best solution of every method, checked with the solution checker's data
    and formulas. Returns a description of every problem found (expected: none)."""
    problems = []
    for inst in INSTANCES:
        nodes = data.nodes[inst]
        cards = [(method_label(m), read_route(inst, m), round(float(data.stats[inst][m]["min"]))) for m in METHODS]
        best_key = min(data.grid_best[inst], key=lambda key: (int(data.grid_best[inst][key]["objective"]), key))
        row = data.grid_best[inst][best_key]
        cards.append((f"Best of Section 6: {key_label(best_key)}", [int(v) for v in row["route"].split()][:-1],
                      int(row["objective"])))
        rendered = []
        for label, route, reported in cards:
            checked = checker_objective(data.checker[inst], route)
            if checked is None:
                status = '<span class="bad">not a valid solution</span>'
                problems.append(f"{inst} {label}: not a valid solution")
            elif checked == reported:
                status = f"solution checker: f = {checked} ✓"
            else:
                status = f'<span class="bad">solution checker: f = {checked} ≠ {reported}</span>'
                problems.append(f"{inst} {label}: checker {checked} != reported {reported}")
            rendered.append(f'<div class="card"><div class="cardhead"><b>{esc(label)}</b><span>f = {reported}</span>'
                            f'</div>{solution_svg(nodes, route, f"{inst}: {label}")}<div class="status">{status}</div>'
                            f'<div class="nodes">{" ".join(str(node) for node in route)}</div></div>')
        for start in range(0, len(rendered), 6):
            heading = (f"<h2>7. Best solutions — {inst}</h2><p>The best solution of every method (the lowest "
                       f"objective in 200 runs) and the best solution of all 63 configurations of Section 6. Node "
                       f"indices start from 0; the cycle returns from the last listed node to the first.</p>"
                       if start == 0 else f"<h2>7. Best solutions — {inst} (continued)</h2>")
            report.page(f'{heading}{cost_legend(nodes)}<div class="cards">{"".join(rendered[start:start + 6])}</div>')
    return problems


# --------------------------------------------------------------------------- observations

def main_facts(data: Data) -> dict:
    gap = {(i, k): pct(data.avg(i, f"candidate_k{k}"), data.avg(i, "steepest_2opt")) for i in INSTANCES for k in K_VALUES}
    speed = {(i, k): data.run_ms(i, "steepest_2opt") / data.run_ms(i, f"candidate_k{k}") for i in INSTANCES for k in K_VALUES}
    with_lists = {(i, k): data.run_ms(i, f"candidate_k{k}") + data.list_ms(i, f"candidate_k{k}")
                  for i in INSTANCES for k in K_VALUES}
    return {
        "gap": gap,
        "speed": speed,
        # smallest K from which every longer list is within 0.5 % of the full neighbourhood on both instances
        "k_close": next((k for k in K_VALUES if all(abs(gap[i, x]) <= 0.5 for i in INSTANCES for x in K_VALUES if x >= k)),
                        None),
        # smallest K from which every longer list is slower than the full neighbourhood on both instances
        "k_slower": next((k for k in K_VALUES if all(speed[i, x] < 1 for i in INSTANCES for x in K_VALUES if x >= k)), None),
        "faster": [k for k in K_VALUES if all(speed[i, k] > 1 for i in INSTANCES)],
        "lists_faster": [k for k in K_VALUES if all(with_lists[i, k] < data.run_ms(i, "steepest_2opt") for i in INSTANCES)],
        "list_times": [data.list_ms(i, f"candidate_k{k}") for i in INSTANCES for k in K_VALUES],
        "list_to_run": [data.list_ms(i, f"candidate_k{k}") / data.run_ms(i, f"candidate_k{k}")
                        for i in INSTANCES for k in K_VALUES],
    }


def main_observations(data: Data) -> str:
    facts = main_facts(data)
    gap, speed, k_close, k_slower = facts["gap"], facts["speed"], facts["k_close"], facts["k_slower"]
    faster, lists_faster, list_times = facts["faster"], facts["lists_faster"], facts["list_times"]
    items = []
    if k_close is not None:
        items.append(f"<b>Quality.</b> From K = {k_close} on, the average objective of the candidate search stays within "
                     f"0.5 % of the full neighbourhood on both instances (K = {k_close}: "
                     f"{signed_pct(data.avg('TSPA', f'candidate_k{k_close}'), data.avg('TSPA', 'steepest_2opt'))} on TSPA, "
                     f"{signed_pct(data.avg('TSPB', f'candidate_k{k_close}'), data.avg('TSPB', 'steepest_2opt'))} on TSPB). "
                     f"Very short lists lose a lot: K = 1 is {gap['TSPA', 1]:+.0f} % / {gap['TSPB', 1]:+.0f} % and "
                     f"K = 5 {gap['TSPA', 5]:+.1f} % / {gap['TSPB', 5]:+.1f} % worse (TSPA / TSPB).")
    if faster:
        items.append(f"<b>Time.</b> The candidate search is faster than the full neighbourhood for "
                     f"{k_set(faster)}: K = 1 by {speed['TSPA', 1]:.1f}× / "
                     f"{speed['TSPB', 1]:.1f}×, K = 10 by {speed['TSPA', 10]:.2f}× / {speed['TSPB', 10]:.2f}×."
                     + (f" From K = {k_slower} on it is slower: such lists contain a large part of all nodes, while "
                        f"the full neighbourhood is scanned row by row with vectorised instructions." if k_slower else ""))
    items.append(f"<b>Candidate lists.</b> Building them takes {min(list_times):.2f}–{max(list_times):.2f} ms "
                 f"({min(facts['list_to_run']):.1f}–{max(facts['list_to_run']):.1f}× the time of a run with the same "
                 f"K). Built once per instance, they cost at most "
                 f"{max(list_times) / 200 * 1000:.1f} µs per run over the 200 runs; built at the beginning of every run, "
                 + (f"only {k_set(lists_faster)} would still be faster than the full "
                    f"neighbourhood." if lists_faster else
                    "no candidate configuration would be faster than the full neighbourhood."))
    return '<ul class="obs">' + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


def grid_facts(data: Data, inst: str) -> dict:
    keys = [(a, b, k) for a in METRICS for b in METRICS for k in K_VALUES]
    full_avg, full_ms = data.grid_avg(inst, FULL_KEY), data.grid_run_ms(inst, FULL_KEY)
    best = min(keys, key=lambda key: (data.grid_avg(inst, key), key))
    better = [key for key in keys if data.grid_avg(inst, key) < full_avg]
    better_and_faster = [key for key in better if data.grid_run_ms(inst, key) < full_ms]
    relative = {}
    for role, index in (("intra", 0), ("inter", 1)):
        for metric in METRICS:
            group = [key for key in keys if key[index] == metric and key[2] >= 10]
            relative[role, metric] = (sum(data.grid_avg(inst, key) for key in group) / len(group) / full_avg,
                                      sum(data.grid_run_ms(inst, key) for key in group) / len(group))
    fastest = min(keys, key=lambda key: data.grid_run_ms(inst, key))
    near_full = [key for key in keys if data.grid_avg(inst, key) <= full_avg * 1.005]
    fastest_near = min(near_full, key=lambda key: data.grid_run_ms(inst, key)) if near_full else None
    return {"full_avg": full_avg, "full_ms": full_ms, "best": best, "better": better,
            "better_and_faster": better_and_faster, "relative": relative, "fastest": fastest,
            "fastest_near": fastest_near}


def grid_notes(data: Data) -> dict[tuple[str, str], str]:
    notes = {}
    for inst in INSTANCES:
        facts = grid_facts(data, inst)
        best = facts["best"]
        notes[inst, "score"] = (
            f"Best average: {key_label(best)} — {data.grid_avg(inst, best):.2f} "
            f"({signed_pct(data.grid_avg(inst, best), facts['full_avg'])} vs. the full neighbourhood). "
            f"{len(facts['better'])} of the 63 configurations have a lower average than the full neighbourhood.")
        fastest, near = facts["fastest"], facts["fastest_near"]
        notes[inst, "time"] = (
            f"Fastest: {key_label(fastest)} — {ms(data.grid_run_ms(inst, fastest))} ms, but with average "
            f"{data.grid_avg(inst, fastest):.0f}. "
            + (f"Fastest configuration within 0.5 % of the full-neighbourhood average: {key_label(near)} — "
               f"{ms(data.grid_run_ms(inst, near))} ms ({facts['full_ms'] / data.grid_run_ms(inst, near):.2f}× faster "
               f"than the full neighbourhood; {ms(data.grid_run_ms(inst, near) + data.grid_list_ms(inst, near))} ms "
               f"with lists)." if near else ""))
    return notes


def conclusions_page(report: Report, data: Data, problems: list[str]) -> None:
    facts = {inst: grid_facts(data, inst) for inst in INSTANCES}
    full = {inst: data.avg(inst, "steepest_2opt") for inst in INSTANCES}
    k10 = {inst: data.avg(inst, "candidate_k10") for inst in INSTANCES}
    speed10 = {inst: data.run_ms(inst, "steepest_2opt") / data.run_ms(inst, "candidate_k10") for inst in INSTANCES}
    rel = {inst: facts[inst]["relative"] for inst in INSTANCES}
    inter_cost = [100 * (rel[i]["inter", "cost"][0] / min(rel[i]["inter", "distance"][0],
                                                            rel[i]["inter", "distance_plus_cost"][0]) - 1) for i in INSTANCES]
    intra_cost = [100 * (rel[i]["intra", "cost"][0] / min(rel[i]["intra", "distance"][0],
                                                            rel[i]["intra", "distance_plus_cost"][0]) - 1) for i in INSTANCES]
    intra_cost_time = [rel[i]["intra", "cost"][1] / rel[i]["intra", "distance"][1] for i in INSTANCES]
    inter_same = all(abs(rel[i]["inter", "distance"][0] - rel[i]["inter", "distance_plus_cost"][0]) < 0.002
                     for i in INSTANCES)
    small_k = {inst: (data.grid_avg(inst, ("distance_plus_cost", "distance_plus_cost", 5)),
                      data.grid_avg(inst, ("distance", "distance_plus_cost", 5))) for inst in INSTANCES}
    winners = []
    for inst in INSTANCES:
        best = facts[inst]["best"]
        winners.append(f"{inst}: {key_label(best)}, average {data.grid_avg(inst, best):.2f} "
                       f"({signed_pct(data.grid_avg(inst, best), facts[inst]['full_avg'])}) in "
                       f"{ms(data.grid_run_ms(inst, best))} ms vs. {ms(facts[inst]['full_ms'])} ms")
    checked = ("All best solutions shown in Section 7 were checked with the provided solution checker (its node data "
               "and formulas, applied to the node lists): every one is a valid solution and the checker objective "
               "equals the reported one." if not problems else
               "The solution checker reported problems: " + "; ".join(esc(p) for p in problems) + ".")
    main = main_facts(data)
    k_close, k_slower = main["k_close"], main["k_slower"]
    tradeoff = ("<b>K controls the trade-off.</b> Very short lists (K = 1, 5) are the fastest but miss many improving "
                "moves and stop in clearly worse local optima."
                + (f" From K = {k_close} on, the average quality is within 0.5 % of the full neighbourhood and longer "
                   f"lists mostly cost time." if k_close else "")
                + (f" For K ≥ {k_slower} the candidate search was slower than the full neighbourhood: on 200 nodes such "
                   f"lists contain a large part of all nodes, and following them is more expensive per move than the "
                   f"regular, vectorised scan of the full neighbourhood." if k_slower else ""))
    better_counts = [len(facts[i]["better"]) for i in INSTANCES]
    if any(better_counts):
        restricted = ("<b>Restricting the neighbourhood need not hurt.</b> "
                      + " and ".join(f"{count} of the 63 configurations on {inst}"
                                     for inst, count in zip(INSTANCES, better_counts))
                      + " reached a lower average than the full neighbourhood. The steepest search then follows a "
                      "different trajectory and the differences are small, so the full neighbourhood is not a strict "
                      "upper bound on quality.")
    else:
        restricted = ("<b>The full neighbourhood remained the best on average</b>, but the best candidate "
                      "configurations were close to it.")
    intra_similar = all(abs(rel[i]["intra", "distance_plus_cost"][0] - rel[i]["intra", "distance"][0]) < 0.005
                        for i in INSTANCES)
    short_better = all(small_k[i][0] < small_k[i][1] for i in INSTANCES)
    intra_text = (f"<b>Definition of \"nearest\" for 2-opt:</b> cost alone is a poor choice — "
                  f"{intra_cost[0]:+.1f} % (TSPA) and {intra_cost[1]:+.1f} % (TSPB) worse and {intra_cost_time[0]:.1f}× "
                  f"/ {intra_cost_time[1]:.1f}× slower than distance, because the cheapest nodes become candidates of "
                  f"every node."
                  + (" Distance + cost was about as good as distance." if intra_similar else "")
                  + (f" For short lists, distance + cost for both move types was better than the proposed definition: "
                     f"with K = 5 it reached {small_k['TSPA'][0]:.0f} instead of {small_k['TSPA'][1]:.0f} (TSPA) and "
                     f"{small_k['TSPB'][0]:.0f} instead of {small_k['TSPB'][1]:.0f} (TSPB)." if short_better else ""))
    ratio = main["list_to_run"]
    items = [
        f"<b>Candidate moves make the steepest local search faster without losing quality, if the lists are not too "
        f"long.</b> With K = 10 and the proposed definition of \"nearest\", a run was {speed10['TSPA']:.2f}× (TSPA) and "
        f"{speed10['TSPB']:.2f}× (TSPB) faster than with the full neighbourhood, and the average objective differed by "
        f"{signed_pct(k10['TSPA'], full['TSPA'])} and {signed_pct(k10['TSPB'], full['TSPB'])}.",
        tradeoff,
        restricted,
        f"<b>Definition of \"nearest\" for exchanges:</b> distance and distance + cost gave "
        f"{'practically the same' if inter_same else 'similar'} quality, while cost alone was "
        f"{inter_cost[0]:+.1f} % (TSPA) and {inter_cost[1]:+.1f} % (TSPB) worse, averaged over K ≥ 10: a node that is "
        f"cheap but far away rarely makes a good replacement.",
        intra_text,
        "<b>Best configurations</b> (lowest average) — " + "; ".join(winners) + ".",
        f"<b>Candidate lists must be reused.</b> Building them took {min(ratio):.1f}–{max(ratio):.1f}× the time of a "
        f"local-search run with the same K (Table 2). Built once per instance, the cost is negligible. Built at the "
        f"beginning of every run, "
        + (f"only {k_set(main['lists_faster'])} would remain faster than the full neighbourhood"
           if main["lists_faster"] else "no list size would remain faster than the full neighbourhood")
        + " (\"with lists\" in Tables 2, 4 and 6).",
        checked,
    ]
    report.page('<h2>8. Conclusions</h2><ul class="conclusions">' + "".join(f"<li>{item}</li>" for item in items) +
                f'</ul><h2>9. Source code</h2><p>The complete source code, the evaluation files and this report '
                f'generator are available at <a href="{REPOSITORY_URL}">{esc(REPOSITORY_URL)}</a>. Build with CMake '
                f'(Release), then run <code>lab04 --seed 20260404</code> (main experiment), '
                f'<code>lab04 --seed 20260404 --ranking-experiment</code> (Section 6) and '
                f'<code>python generate_report.py</code>.</p>')


# ------------------------------------------------------------------------------- styling

CSS = """
@page { size: A4; margin: 0; }
@page wide { size: A4 landscape; margin: 0; }
* { box-sizing: border-box; }
html { background: #d9d8d3; }
body { margin: 0; font-family: "Segoe UI", system-ui, -apple-system, sans-serif; font-size: 9.6pt; line-height: 1.42;
       color: #0b0b0b; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 210mm; height: 297mm; padding: 15mm 16mm 0; background: #ffffff; position: relative; overflow: hidden;
        break-after: page; margin: 0 auto; }
.page.wide { width: 297mm; height: 210mm; padding: 11mm 13mm 0; page: wide; }
.content { height: calc(297mm - 15mm - 15mm); overflow: hidden; }
.page.wide .content { height: calc(210mm - 11mm - 13mm); }
.footer { position: absolute; left: 16mm; right: 16mm; bottom: 7mm; display: flex; justify-content: space-between;
          font-size: 7.5pt; color: #52514e; border-top: 0.5pt solid #e1e0d9; padding-top: 1.8mm; }
.page.wide .footer { left: 13mm; right: 13mm; bottom: 5mm; }
h1 { font-size: 21pt; line-height: 1.15; margin: 1mm 0 3mm; font-weight: 650; }
h2 { font-size: 13pt; margin: 5mm 0 2mm; font-weight: 650; }
.content > h2:first-child { margin-top: 0; }
p { margin: 0 0 2.4mm; }
ul { margin: 0 0 2.5mm; padding-left: 5mm; }
li { margin-bottom: 1.4mm; }
a { color: #256abf; text-decoration: none; }
code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 0.92em; white-space: nowrap; }
.nowrap { white-space: nowrap; }
.title { border-bottom: 1.2pt solid #2a78d6; padding-bottom: 4mm; margin-bottom: 6mm; }
.kicker { font-size: 9pt; font-weight: 650; color: #256abf; letter-spacing: 0.04em; text-transform: uppercase; }
.meta { color: #52514e; font-size: 9.4pt; }
.formula { text-align: center; font-size: 11pt; margin: 3mm 0; }
pre.code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 7.8pt; line-height: 1.36; background: #f7f7f5;
           border: 0.5pt solid #e1e0d9; border-radius: 2mm; padding: 2.6mm 3.5mm; margin: 0 0 3mm; white-space: pre; }
pre.code .c { color: #52514e; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
caption { caption-side: top; text-align: left; font-weight: 650; padding: 0 0 1.5mm; font-size: 9.2pt; }
table.results { margin: 0 0 5mm; font-size: 8.8pt; }
table.results th, table.results td { border-bottom: 0.5pt solid #e1e0d9; padding: 1.4mm 2mm; text-align: left; }
table.results thead th { background: #f0efec; font-weight: 650; border-bottom: 0.8pt solid #c3c2b7; }
table.results tbody th { font-weight: 600; }
table.results td { white-space: nowrap; }
table.results td.best { font-weight: 700; }
table.times { font-size: 8.3pt; }
.sub { font-size: 0.88em; }
.tablehead { font-weight: 650; font-size: 10pt; margin: 0 0 2mm; }
table.grid { font-size: 8.4pt; }
table.grid th, table.grid td { border: 0.5pt solid #e1e0d9; padding: 1.0mm 1.3mm; vertical-align: middle; }
table.grid thead th { background: #f0efec; font-weight: 650; text-align: center; border-bottom: 0.8pt solid #c3c2b7; }
table.grid tbody th { text-align: left; font-weight: 600; background: #fafaf8; width: 27mm; }
table.grid .sub { display: block; font-weight: 400; }
table.grid td { text-align: center; }
table.grid td .main { display: block; font-weight: 600; }
table.grid tr.first > * { border-top: 0.9pt solid #c3c2b7; }
table.grid.time { font-size: 8.1pt; }
td.s3 { background: #6da7ec; } td.s2 { background: #9ec5f4; } td.s1 { background: #cde2fb; }
td.s3 .main { font-weight: 800; }
.note { font-size: 8.4pt; margin-top: 2.2mm; margin-bottom: 0; }
.chip { display: inline-block; padding: 0 2mm; margin: 0 1mm; border-radius: 1mm; }
.chip.s3 { background: #6da7ec; } .chip.s2 { background: #9ec5f4; } .chip.s1 { background: #cde2fb; }
.legend { font-size: 8.2pt; margin: 0 0 3mm; display: flex; flex-wrap: wrap; align-items: center; gap: 1mm 3.5mm; }
.legend .key { display: inline-flex; align-items: center; gap: 1mm; }
.cards { display: grid; grid-template-columns: 1fr 1fr; gap: 4mm 6mm; }
.card { break-inside: avoid; }
.cardhead { display: flex; justify-content: space-between; font-size: 8.4pt; margin-bottom: 1mm; gap: 2mm; }
.cardhead b { font-weight: 650; }
.cardhead span { white-space: nowrap; }
svg.plot { width: 100%; height: auto; display: block; }
.status { font-size: 7.8pt; margin: 1mm 0 0.6mm; }
.nodes { font-family: "Cascadia Mono", Consolas, monospace; font-size: 6.6pt; line-height: 1.32; word-spacing: 0.3mm; }
.bad { color: #d03b3b; font-weight: 700; }
.obs { font-size: 9.2pt; }
.obs li { margin-bottom: 1.6mm; }
.conclusions li { margin-bottom: 2.4mm; }
@media screen { .page { margin: 0 auto 6mm; } }
"""

OVERFLOW_SCRIPT = """<script>
document.addEventListener('DOMContentLoaded', () => {
  for (const page of document.querySelectorAll('.page')) {
    const content = page.querySelector('.content');
    const extra = content.scrollHeight - content.clientHeight;
    if (extra > 1) page.setAttribute('data-overflow', String(extra));
  }
});
</script>"""


# ---------------------------------------------------------------------------- the report

def build_html() -> tuple[str, list[str]]:
    data = Data()
    report = Report()
    first_page(report)
    algorithm_pages(report)
    main_results_page(report, data, main_observations(data))
    grid_pages(report, data, grid_notes(data))
    problems = best_solution_pages(report, data)
    conclusions_page(report, data, problems)
    document = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Lab 04 — Candidate moves</title>'
                f'<style>{CSS}</style></head><body>{"".join(report.pages)}{OVERFLOW_SCRIPT}</body></html>')
    return document, problems


def find_browser() -> str:
    candidates = [os.environ.get("REPORT_BROWSER", "")]
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 os.environ.get("LOCALAPPDATA", "")):
        if base:
            candidates += [str(Path(base) / "Microsoft/Edge/Application/msedge.exe"),
                           str(Path(base) / "Google/Chrome/Application/chrome.exe")]
    candidates += [shutil.which(name) or "" for name in ("msedge", "google-chrome", "chromium", "chrome")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("no Chromium-based browser found; set REPORT_BROWSER to msedge or chrome")


def run_browser(browser: str, arguments: list[str]) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as profile:
        return subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                               f"--user-data-dir={profile}", *arguments],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)


def main() -> None:
    BUILD.mkdir(exist_ok=True)
    document, problems = build_html()
    REPORT_HTML.write_text(document, encoding="utf-8")
    print(f"wrote {REPORT_HTML}")
    if problems:
        print("solution checker problems:\n  " + "\n  ".join(problems))
    if "--html-only" in sys.argv:
        return
    browser = find_browser()
    url = REPORT_HTML.resolve().as_uri()
    dom = run_browser(browser, ["--dump-dom", url]).stdout
    overflow = re.findall(r'<section class="page[^"]*" id="(page-\d+)" data-overflow="(\d+)"', dom)
    if overflow:
        print("warning: content does not fit on " + ", ".join(f"{page} (+{extra}px)" for page, extra in overflow))
    if REPORT_PDF.exists():
        REPORT_PDF.unlink()
    result = run_browser(browser, ["--no-pdf-header-footer", f"--print-to-pdf={REPORT_PDF}", url])
    if not REPORT_PDF.exists():
        sys.exit(f"printing failed: {result.stderr}")
    pages = len(re.findall(rb"/Type\s*/Page[^s]", REPORT_PDF.read_bytes()))
    print(f"wrote {REPORT_PDF} ({pages} pages)")


if __name__ == "__main__":
    main()
