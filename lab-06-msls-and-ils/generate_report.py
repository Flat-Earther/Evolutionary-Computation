"""Generate the Lab 06 report (multiple start and iterated local search) as a PDF.

The report is built as HTML with explicit A4 pages and printed to PDF by a headless
Chromium-based browser (Microsoft Edge or Google Chrome). Inputs are the files written by the
lab06 executable:

    build/lab06.exe --seed 20260404 --perturbation-experiment

and, for the comparison with earlier methods, the evaluation files of assignments 2, 2.5 and 3. The
plots of the best solutions are the SVG files the executable writes to evaluation/plots.

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
REPOSITORY_URL = "https://github.com/Flat-Earther/Evolutionary-Computation/tree/main/lab-06-msls-and-ils"
INSTANCES = ("TSPA", "TSPB")
RUNS = 20
MSLS_ITERATIONS = 400

# Best methods of the earlier assignments: (evaluation folder, method id, label). Their objective
# values come from those assignments (200 solutions each, one per start node or random solution).
PREVIOUS = (
    ("lab-02-greedy-regret-heuristics", "weighted_cycle",
     "Greedy weighted 2-regret, cycle (assignment 2)"),
    ("lab-02,5-greedy-regret-heuristics-the-other-way", "weighted_path_reversed",
     "Greedy weighted 2-regret, path, reversed traversal (assignment 2.5)"),
    ("lab-03-local-search", "greedy_steepest_2opt",
     "Steepest local search from greedy solutions (assignment 3)"),
)
SINGLE, MSLS, ILS = "local_search", "msls", "ils"
LABELS = {
    SINGLE: "Steepest local search from a random solution, one run",
    MSLS: "Multiple start local search (MSLS)",
    ILS: "Iterated local search (ILS)",
}
CHOSEN = "db1_seg4"

# Two series of Figure 1: categorical slots 1 and 2 of the reference palette (validated: light mode on white).
SERIES_COLOR = {MSLS: "#2a78d6", ILS: "#eb6834"}


# ----------------------------------------------------------------------------------- data

def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        sys.exit(f"missing {path} - run the experiments first (see the README)")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class Data:
    def __init__(self) -> None:
        def by_method(name: str, key: str = "method_name") -> dict[str, dict[str, dict[str, str]]]:
            return {i: {r[key]: r for r in read_csv(EVALUATION / f"{i}_{name}.csv")} for i in INSTANCES}

        self.stats = by_method("stats")
        self.times = by_method("times")
        self.ls_runs = by_method("ls_runs")
        self.perturbations = {i: read_csv(EVALUATION / f"{i}_perturbations.csv") for i in INSTANCES}
        self.runs = {i: read_csv(EVALUATION / f"{i}_runs.csv") for i in INSTANCES}
        self.previous = {i: {} for i in INSTANCES}
        for folder, method, _ in PREVIOUS:
            for inst in INSTANCES:
                rows = {r["method_name"]: r for r in read_csv(ROOT.parent / folder / "evaluation" / f"{inst}_stats.csv")}
                self.previous[inst][method] = rows[method]
        self.nodes = {i: load_nodes(i) for i in INSTANCES}
        self.checker = load_checker_tables()

    def avg(self, inst: str, method: str) -> float:
        row = self.stats[inst].get(method) or self.previous[inst][method]
        return float(row["avg"])

    def value(self, inst: str, method: str, field: str) -> float:
        row = self.stats[inst].get(method) or self.previous[inst][method]
        return float(row[field])

    def run_ms(self, inst: str, method: str) -> float:
        return float(self.times[inst][method]["average_ms"])

    def objectives(self, inst: str, method: str) -> list[int]:
        return [int(r["objective"]) for r in self.runs[inst] if r["method_name"] == method]

    def perturbation(self, inst: str, perturbation_id: str) -> dict[str, str]:
        return next(r for r in self.perturbations[inst] if r["perturbation"] == perturbation_id)


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


def num(value: float, decimals: int = 0) -> str:
    """Number with thin spaces between thousands."""
    return f"{value:,.{decimals}f}".replace(",", " ")


def ms(value: float | str, decimals: int = 1) -> str:
    return f"{float(value):.{decimals}f}"


def pct(value: float, reference: float) -> float:
    return 100.0 * (value / reference - 1.0)


def signed_pct(value: float, reference: float, decimals: int = 1) -> str:
    return f"{pct(value, reference):+.{decimals}f} %".replace("-", "−")


def objective_cell(row: dict[str, str]) -> str:
    return f"{float(row['avg']):.2f} ({float(row['min']):.0f} – {float(row['max']):.0f})"


# ------------------------------------------------------------------------------- figures

def embedded_plot(inst: str, method: str, label: str) -> str:
    """The program's plot of the method's best solution (evaluation/plots), inlined. Its small
    title is dropped (the card header repeats it) and the view is cropped to the plotted area."""
    path = EVALUATION / "plots" / f"{inst}_{method}.svg"
    if not path.exists():
        sys.exit(f"missing {path} - run the lab06 experiment first (see the README)")
    svg = re.sub(r"<text\b.*?</text>\s*", "", path.read_text(encoding="utf-8"), flags=re.S)
    opening = (f'<svg class="plot" viewBox="26 26 848 848" role="img" '
               f'aria-label="{esc(f"{inst}: best solution of {label}")}">')
    svg, replaced = re.subn(r"<svg\b[^>]*>", lambda _: opening, svg, count=1)
    if replaced != 1:
        sys.exit(f"{path} is not an SVG plot")
    return svg.strip()


def plot_legend(nodes: list[tuple[int, int, int]]) -> str:
    """Legend of the program's plots: node colour (blue to red) and radius follow the node cost."""
    costs = [n[2] for n in nodes]
    cmin, cmax = min(costs), max(costs)
    items = []
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        color = f"rgb({round(255 * t)},{round(80 * (1 - t))},{round(255 * (1 - t))})"
        items.append(f'<span class="key"><svg width="15" height="15" viewBox="0 0 15 15"><circle cx="7.5" cy="7.5" '
                     f'r="{(4 + 8 * t) * 0.5:.2f}" fill="{color}" stroke="#222" stroke-width="0.5"/></svg>'
                     f'{round(cmin + t * (cmax - cmin))}</span>')
    return ('<div class="legend"><span>Node cost (colour and size):</span>' + "".join(items) +
            '<span class="key"><svg width="20" height="10" viewBox="0 0 20 10"><line x1="1" y1="5" x2="19" y2="5" '
            'stroke="#333333" stroke-width="1.6"/></svg>cycle (nodes off it are not selected)</span></div>')


def nice_step(span: float) -> float:
    raw = span / 6
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        if factor * magnitude >= raw:
            return factor * magnitude
    return 10 * magnitude


def beeswarm(xs: list[float], radius: float) -> list[tuple[float, int]]:
    """Places dots on one row: every dot gets the level closest to the row line (0, -1, 1, -2, ...)
    at which it does not overlap a dot placed before it."""
    level_order = [0]
    for step in range(1, len(xs) + 1):
        level_order += [-step, step]
    placed: list[tuple[float, int]] = []
    for x in xs:
        for level in level_order:
            if all(abs(x - px) >= 2 * radius + 1 or level != pl for px, pl in placed):
                placed.append((x, level))
                break
    return placed


def runs_figure(data: Data) -> str:
    """Objective of the 20 runs of MSLS and ILS, one panel per instance on its own axis; every dot
    is one run, the vertical tick is the average."""
    width, left, right = 670.0, 70.0, 640.0
    radius, row_gap, level_gap, top = 4.0, 30.0, 8.5, 30.0
    panels = []
    for inst in INSTANCES:
        values = {method: sorted(data.objectives(inst, method)) for method in (MSLS, ILS)}
        low = min(min(v) for v in values.values())
        high = max(max(v) for v in values.values())
        step = nice_step(high - low)
        axis_low = math.floor(low / step) * step
        axis_high = math.ceil(high / step) * step

        def x(value: float) -> float:
            return left + (right - left) * (value - axis_low) / (axis_high - axis_low)

        # Every row is as tall as its stack of dots; the average label of a row sits above it.
        rows = []
        y = top
        for method in (MSLS, ILS):
            placed = beeswarm([x(v) for v in values[method]], radius)
            band = 2 * max(abs(level) for _, level in placed) * level_gap + 2 * radius + 8
            rows.append((method, placed, sum(values[method]) / len(values[method]), y + band / 2, band))
            y += band + row_gap
        axis_y = y - row_gap + 10
        height = axis_y + 22
        parts = [f'<svg class="figure" viewBox="0 0 {width:.0f} {height:.0f}" role="img" '
                 f'aria-label="{inst}: objective of {RUNS} runs of MSLS and ILS">']
        parts.append(f'<text x="0" y="14" class="panel">{inst}</text>')
        tick = axis_low
        while tick <= axis_high + 1e-9:
            parts.append(f'<line x1="{x(tick):.1f}" y1="{top - 4:.1f}" x2="{x(tick):.1f}" y2="{axis_y:.1f}" '
                         f'stroke="#e1e0d9" stroke-width="1"/>')
            parts.append(f'<text x="{x(tick):.1f}" y="{axis_y + 14:.1f}" text-anchor="middle" class="tick">'
                         f'{num(tick)}</text>')
            tick += step
        parts.append(f'<line x1="{left:.1f}" y1="{axis_y:.1f}" x2="{right:.1f}" y2="{axis_y:.1f}" stroke="#c3c2b7" '
                     f'stroke-width="1"/>')
        for method, placed, mean, center, band in rows:
            parts.append(f'<text x="{left - 12:.1f}" y="{center + 4:.1f}" text-anchor="end" class="row">'
                         f'{"MSLS" if method == MSLS else "ILS"}</text>')
            for px, level in placed:
                parts.append(f'<circle cx="{px:.1f}" cy="{center + level * level_gap:.1f}" r="{radius}" '
                             f'fill="{SERIES_COLOR[method]}" stroke="#ffffff" stroke-width="1.5"/>')
            mx = x(mean)
            half = band / 2 - 1
            parts.append(f'<line x1="{mx:.1f}" y1="{center - half:.1f}" x2="{mx:.1f}" y2="{center + half:.1f}" '
                         f'stroke="#0b0b0b" stroke-width="2"/>')
            parts.append(f'<text x="{mx:.1f}" y="{center - half - 3:.1f}" text-anchor="middle" class="value">'
                         f'avg {num(mean)}</text>')
        parts.append("</svg>")
        panels.append("".join(parts))
    legend = "".join(f'<span class="key"><svg width="12" height="12" viewBox="0 0 12 12"><circle cx="6" cy="6" r="4.5" '
                     f'fill="{SERIES_COLOR[m]}"/></svg>{"MSLS" if m == MSLS else "ILS"}</span>' for m in (MSLS, ILS))
    legend += ('<span class="key"><svg width="12" height="12" viewBox="0 0 12 12"><line x1="6" y1="0" x2="6" y2="12" '
               f'stroke="#0b0b0b" stroke-width="2"/></svg>average of the {RUNS} runs</span>')
    return f'<div class="legend"><span>One dot per run:</span>{legend}</div>{"".join(panels)}'


# --------------------------------------------------------------------------------- pages

class Report:
    def __init__(self) -> None:
        self.pages: list[str] = []

    def page(self, body: str) -> None:
        number = len(self.pages) + 1
        footer = (f'<div class="footer"><span>Evolutionary Computation · Assignment 6 · MSLS and ILS</span>'
                  f'<span>{esc(AUTHORS[0][0])}, {esc(AUTHORS[1][0])} · page {number}</span></div>')
        self.pages.append(f'<section class="page" id="page-{number}"><div class="content">{body}</div>{footer}'
                          f'</section>')


def first_page(report: Report, data: Data) -> None:
    authors = " &nbsp;·&nbsp; ".join(f"{esc(name)} ({esc(index)})" for name, index in AUTHORS)
    limits = " and ".join(f"{ms(data.times[i][ILS]['time_limit_ms'])} ms ({i})" for i in INSTANCES)
    report.page(f"""
<div class="title">
  <div class="kicker">Evolutionary Computation · Assignment 6 · Report</div>
  <h1>Multiple start local search (MSLS) and iterated local search (ILS)</h1>
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
<p>The goal is to extend local search in two simple ways. Both use the same basic local search: the steepest local
search of the earlier assignments, with <b>2-opt</b> (exchange of two edges) as the intra-route move and the
<b>exchange</b> of a selected and a not selected node as the inter-route move.</p>
<ul>
<li><b>Multiple start local search (MSLS)</b> — {MSLS_ITERATIONS} runs of local search, each from a new random
solution; the result of one run of MSLS is the best of the {MSLS_ITERATIONS} local optima.</li>
<li><b>Iterated local search (ILS)</b> — local search from one random solution, then repeatedly: perturb the
current solution, run local search from the perturbed solution and accept the new local optimum if it is better.
ILS stops after the average running time of MSLS on the same instance ({limits}).</li>
</ul>
<p>The perturbation was designed for this problem (Section 2.1): one <b>double-bridge</b> move changes the order of
the nodes in a way a single 2-opt move cannot undo, and the <b>replacement of a segment of four consecutive
nodes</b> by random not selected nodes changes the selection. Each method was run {RUNS} times per instance. For
comparison the report also includes the best construction heuristics (assignments 2 and 2.5) and the best local
searches (assignment 3, and the single run of the basic local search).</p>
<p>The pseudocode is in Section 3, the experimental setup in Section 4, the results in Section 5, the best solutions
with their visualisation and node lists in Section 6 and the conclusions in Section 7.</p>""")


PSEUDOCODE_1 = """<span class="c">Notation</span>
  n nodes, m = ⌈n/2⌉ selected; d(u, v) distance matrix; c(v) node cost
  S[0..m−1]  cycle of the selected nodes (positions modulo m)

<b>RANDOM-SOLUTION</b>()
  P <- random permutation of {0, ..., n−1}             <span class="c">// std::shuffle, mt19937</span>
  return S = (P[0], ..., P[m−1])

<b>LOCAL-SEARCH</b>(S)                                    <span class="c">// basic steepest local search</span>
  repeat
    (move, Δ) <- the best move of S:
        2-OPT(i, j): reverse S[i..j]
            Δ = d(S[i−1], S[j]) + d(S[i], S[j+1]) − d(S[i−1], S[i]) − d(S[j], S[j+1])
        EXCHANGE(p, v), v not selected: S[p] <- v
            Δ = d(S[p−1], v) + d(v, S[p+1]) + c(v) − d(S[p−1], S[p]) − d(S[p], S[p+1]) − c(S[p])
    if Δ >= 0: return S                                  <span class="c">// local optimum</span>
    apply move to S

<b>MSLS</b>()                                               <span class="c">// one run</span>
  best <- none
  repeat 400 times
    S <- LOCAL-SEARCH(RANDOM-SOLUTION())
    if best = none or f(S) < f(best): best <- S
  return best

<b>ILS</b>(T)                                  <span class="c">// T = average running time of MSLS on the instance</span>
  x <- LOCAL-SEARCH(RANDOM-SOLUTION())
  while the elapsed time < T:
    y <- LOCAL-SEARCH(PERTURB(x))
    if f(y) < f(x): x <- y                               <span class="c">// accept only a better local optimum</span>
  return x"""

PSEUDOCODE_2 = """<b>PERTURB</b>(x)                                      <span class="c">// returns a perturbed copy y of x</span>
  y <- copy of x
  <span class="c">// double bridge</span>
  draw i, j, k uniformly from {1, ..., m−1} until they are distinct; sort them so that i < j < k
  A <- y[0..i−1];  B <- y[i..j−1];  C <- y[j..k−1];  D <- y[k..m−1]
  y <- A C B D                                     <span class="c">// B and C swap places, nothing is reversed</span>
  <span class="c">// replacement of a segment of 4 nodes</span>
  U <- the nodes that are not selected in y
  draw a start position p uniformly from {0, ..., m−1}
  for t = 0, 1, 2, 3:
    draw v uniformly from U;  U <- U \\ {v}
    y[(p + t) mod m] <- v                          <span class="c">// the replaced nodes are not drawn again</span>
  return y"""


def algorithm_pages(report: Report, data: Data) -> None:
    report.page(f"""
<h2>2.1 Perturbation</h2>
<p>A perturbation has to lead ILS out of the basin of attraction of the current local optimum, but not so far that
the next local search starts almost from scratch. The proposed perturbation therefore changes both parts of a
solution a little, in ways the local search cannot simply undo with one move:</p>
<ol>
<li><b>Double bridge.</b> Three distinct cut positions 0 &lt; i &lt; j &lt; k ≤ m − 1 are drawn uniformly; the route
S = A B C D (A = S[0..i−1], B = S[i..j−1], C = S[j..k−1], D = S[k..m−1]) becomes A C B D. The segments B and C swap
places without being reversed, so the three edges at the cuts are replaced. A 2-opt move reverses a segment and
cannot undo this in one step.</li>
<li><b>Replacement of a segment.</b> A start position p is drawn uniformly; the four consecutive selected nodes
S[p], S[p+1], S[p+2], S[p+3] (cyclically) are replaced by four distinct nodes drawn uniformly from the nodes that
were not selected, in the order of drawing. The replaced nodes cannot come back in the same perturbation; the local
search may later bring them back with exchanges.</li>
</ol>
<p>Both steps are applied once in every iteration, the double bridge first. The parameters (one double bridge,
a segment of four nodes) were chosen in a comparison of perturbations (Table 4). The new local optimum is accepted
only if it is strictly better than the current solution.</p>
<h2>3. Algorithms (pseudocode)</h2>
<pre class="code">{PSEUDOCODE_1}</pre>""")
    report.page(f"""
<pre class="code">{PSEUDOCODE_2}</pre>
<h2>3.1 Implementation</h2>
<ul>
<li><b>Basic local search.</b> The steepest local search is implemented with the list of improving moves of
assignment 5 (moves evaluated after each move only where the solution changed; ties broken in the scan order of the
plain steepest search). It applies exactly the same moves as the plain steepest local search, about twice as fast.
Only the change Δ of the objective is computed for every move.</li>
<li><b>Iterations of ILS.</b> Every iteration copies the current local optimum, perturbs the copy and runs the local
search from it; the local search evaluates all moves of the perturbed solution and then only the new ones, so a
local optimum near the start is reached after a few moves.</li>
<li><b>Time limit of ILS.</b> The limit is checked before every iteration; the time of an ILS run includes its first
local search from the random solution.</li>
<li><b>Randomness.</b> Every run of MSLS and of ILS has its own random generator (mt19937, seeded from the seed of
the experiment, the instance and the run), so the experiment can be repeated; ILS stops after a time, so its results
can differ slightly between repetitions.</li>
<li><b>Verification.</b> Every reported solution is checked to be a valid cycle of 100 distinct nodes, its objective
is recomputed from scratch, and a run of the steepest local search from it must not find an improving move. The best
solutions were also checked with the provided solution checker (Section 6).</li>
</ul>
<h2>4. Computational experiment</h2>
<ul>
<li><b>Runs.</b> On each instance, MSLS was run {RUNS} times, then ILS {RUNS} times. One run of MSLS performs
{MSLS_ITERATIONS} local searches; ILS stops after the average running time of the {RUNS} MSLS runs on the same
instance, measured in the same execution. Every ILS run starts from its own random solution.</li>
<li><b>Single local search.</b> The row "one run" of the basic local search summarises all
{num(RUNS * MSLS_ITERATIONS)} local searches performed inside MSLS (each from a random solution).</li>
<li><b>Earlier methods.</b> The objective values of the best construction heuristics (assignments 2 and 2.5) and of
the best local search of assignment 3 are taken from those assignments (200 solutions each). Their running times were
measured with earlier implementations and are not comparable, so they are not repeated here.</li>
<li><b>Perturbations.</b> In an additional experiment, ILS was also run {RUNS} times per instance with six other
perturbations and the same time limit (Table 4).</li>
<li><b>Environment.</b> AMD Ryzen 7 7840HS, Windows 11, mains power; GCC 16.2 (MSYS2 UCRT64), CMake Release build
(<span class="nowrap">-O3 -march=x86-64-v2</span>), single thread.</li>
</ul>""")


def results_pages(report: Report, data: Data) -> None:
    methods = [method for _, method, _ in PREVIOUS] + [SINGLE, MSLS, ILS]
    labels = {method: label for _, method, label in PREVIOUS} | LABELS
    best_avg = {i: min(data.avg(i, m) for m in methods) for i in INSTANCES}
    score_rows = []
    for method in methods:
        cells = []
        for inst in INSTANCES:
            row = data.stats[inst].get(method) or data.previous[inst][method]
            cls = ' class="best"' if data.avg(inst, method) == best_avg[inst] else ""
            cells.append(f"<td{cls}>{objective_cell(row)}</td>")
        separator = ' class="first"' if method == SINGLE else ""
        score_rows.append(f"<tr{separator}><th>{esc(labels[method])}</th>{''.join(cells)}</tr>")
    time_rows = []
    for method in (SINGLE, MSLS, ILS):
        cells = []
        for inst in INSTANCES:
            row = data.times[inst][method]
            decimals = 3 if method == SINGLE else 1
            cells.append(f"<td>{ms(row['average_ms'], decimals)} ({ms(row['minimum_ms'], decimals)} – "
                         f"{ms(row['maximum_ms'], decimals)})</td>")
        time_rows.append(f"<tr><th>{esc(LABELS[method])}</th>{''.join(cells)}</tr>")
    run_rows = []
    for method in (MSLS, ILS):
        cells = []
        for inst in INSTANCES:
            row = data.ls_runs[inst][method]
            if method == MSLS:
                cells.append(f'<td>{MSLS_ITERATIONS} (fixed)</td><td class="num">—</td>')
            else:
                cells.append(f"<td>{num(float(row['average']), 1)} ({num(float(row['minimum']))} – "
                             f"{num(float(row['maximum']))})</td>"
                             f'<td class="num">{float(row["improvements_average"]):.1f}</td>')
        run_rows.append(f"<tr><th>{esc(LABELS[method])}</th>{''.join(cells)}</tr>")
    limits = ", ".join(f"{i} {ms(data.times[i][ILS]['time_limit_ms'])} ms" for i in INSTANCES)
    report.page(f"""
<h2>5. Results</h2>
<table class="results">
<caption>Table 1. Objective function: average (minimum – maximum); the lowest average in bold. The first three rows
are results of earlier assignments; MSLS and ILS: {RUNS} runs each</caption>
<thead><tr><th>Method</th><th>TSPA</th><th>TSPB</th></tr></thead>
<tbody>{''.join(score_rows)}</tbody></table>
<div class="tablehead">Figure 1. Objective of the {RUNS} runs of MSLS and of ILS on each instance</div>
{runs_figure(data)}""")

    order = [row["perturbation"] for row in data.perturbations[INSTANCES[0]]]
    best = {i: min(float(r["avg"]) for r in data.perturbations[i]) for i in INSTANCES}
    perturbation_rows = []
    for perturbation_id in order:
        first = data.perturbation(INSTANCES[0], perturbation_id)
        label = first["label"] + (" (used)" if perturbation_id == CHOSEN else "")
        cells = []
        for inst in INSTANCES:
            row = data.perturbation(inst, perturbation_id)
            cls = ' class="best"' if float(row["avg"]) == best[inst] else ""
            cells.append(f'<td{cls}>{objective_cell(row)}</td><td class="num">{num(float(row["ls_runs_average"]))}</td>')
        perturbation_rows.append(f"<tr><th>{esc(label)}</th>{''.join(cells)}</tr>")
    report.page(f"""
<table class="results times">
<caption>Table 2. Running time of one run in ms: average (minimum – maximum). One run of the basic local search
includes the generation of its random solution; the time limit of ILS was {limits}</caption>
<thead><tr><th>Method</th><th>TSPA</th><th>TSPB</th></tr></thead>
<tbody>{''.join(time_rows)}</tbody></table>
<table class="results times">
<caption>Table 3. Number of runs of the basic local search in one run: average (minimum – maximum), and the average
number of perturbations whose local optimum was accepted (ILS)</caption>
<thead><tr><th rowspan="2">Method</th><th colspan="2">TSPA</th><th colspan="2">TSPB</th></tr>
<tr><th>local searches</th><th class="num">accepted</th><th>local searches</th><th class="num">accepted</th></tr></thead>
<tbody>{''.join(run_rows)}</tbody></table>
<h2>5.1 Comparison of perturbations</h2>
<p>The perturbation of ILS was chosen from the variants in Table 4, each run {RUNS} times per instance with the same
time limit as ILS. The row "used" is the ILS series of Tables 1–3.</p>
<table class="results times">
<caption>Table 4. ILS with different perturbations: objective, average (minimum – maximum), and the average number of
local searches per run; the lowest average in bold. "Segment of k": k consecutive nodes replaced by random not
selected nodes; "10 random moves": each a random 2-opt move or a random exchange</caption>
<thead><tr><th rowspan="2">Perturbation</th><th colspan="2">TSPA</th><th colspan="2">TSPB</th></tr>
<tr><th>objective</th><th class="num">local searches</th><th>objective</th><th class="num">local searches</th></tr>
</thead>
<tbody>{''.join(perturbation_rows)}</tbody></table>""")


def best_solution_pages(report: Report, data: Data) -> list[str]:
    """The program's plots of the best solution of MSLS and ILS, the node lists and a check with the
    solution checker's data and formulas. Returns a description of every problem found (expected: none)."""
    problems = []
    for inst in INSTANCES:
        rendered = []
        for method in (MSLS, ILS):
            route = read_route(inst, method)
            reported = round(data.value(inst, method, "min"))
            checked = checker_objective(data.checker[inst], route)
            if checked is None:
                status = '<span class="bad">not a valid solution</span>'
                problems.append(f"{inst} {method}: not a valid solution")
            elif checked == reported:
                status = f"f = {reported} · solution checker: f = {checked} ✓"
            else:
                status = f'<span class="bad">f = {reported}, solution checker {checked} ≠ {reported}</span>'
                problems.append(f"{inst} {method}: checker {checked} != reported {reported}")
            rendered.append(f'<div class="card"><div class="cardhead"><b>{esc(LABELS[method])}</b></div>'
                            f'<div class="status">{status}</div>{embedded_plot(inst, method, LABELS[method])}'
                            f'<div class="nodes">{" ".join(str(node) for node in route)}</div></div>')
        report.page(f"<h2>6. Best solutions — {inst}</h2><p>The best solution of MSLS and of ILS (the lowest objective in "
                    f"{RUNS} runs), as plotted by the program, with its objective f, the result of the solution checker "
                    f"and the node list. Node indices start from 0; the cycle returns from the last listed node to the "
                    f"first.</p>{plot_legend(data.nodes[inst])}<div class=\"cards\">{''.join(rendered)}</div>")
    return problems


def conclusions_page(report: Report, data: Data, problems: list[str]) -> None:
    ils_avg = {i: data.avg(i, ILS) for i in INSTANCES}
    msls_avg = {i: data.avg(i, MSLS) for i in INSTANCES}
    separated = all(data.value(i, ILS, "max") < data.value(i, MSLS, "min") for i in INSTANCES)
    ls_ratio = {i: float(data.ls_runs[i][ILS]["average"]) / MSLS_ITERATIONS for i in INSTANCES}
    single = {i: data.avg(i, SINGLE) for i in INSTANCES}
    greedy_ls = "greedy_steepest_2opt"
    best_constructive = {i: min(data.avg(i, m) for _, m, _ in PREVIOUS[:2]) for i in INSTANCES}
    msls_vs_greedy = {i: msls_avg[i] < data.avg(i, greedy_ls) for i in INSTANCES}
    accepted = {i: float(data.ls_runs[i][ILS]["improvements_average"]) for i in INSTANCES}
    perturbation = {i: {r["perturbation"]: r for r in data.perturbations[i]} for i in INSTANCES}

    first = (f"<b>ILS is clearly better than MSLS in the same time.</b> The average objective of ILS was "
             f"{num(ils_avg['TSPA'], 2)} instead of {num(msls_avg['TSPA'], 2)} on TSPA "
             f"({signed_pct(ils_avg['TSPA'], msls_avg['TSPA'])}) and {num(ils_avg['TSPB'], 2)} instead of "
             f"{num(msls_avg['TSPB'], 2)} on TSPB ({signed_pct(ils_avg['TSPB'], msls_avg['TSPB'])})"
             + (f"; even the worst ILS run ({num(data.value('TSPA', ILS, 'max'))} / {num(data.value('TSPB', ILS, 'max'))}) "
                f"was better than the best MSLS run ({num(data.value('TSPA', MSLS, 'min'))} / "
                f"{num(data.value('TSPB', MSLS, 'min'))}, TSPA / TSPB, Figure 1)." if separated else "."))
    ils_runs = {i: float(data.ls_runs[i][ILS]["average"]) for i in INSTANCES}
    why = (f"<b>ILS spends its time near good solutions.</b> It performed about {ls_ratio['TSPA']:.1f}× (TSPA) and "
           f"{ls_ratio['TSPB']:.1f}× (TSPB) as many local searches as MSLS in the same time: a local search from a "
           f"perturbed local optimum needs only a few moves, while each local search of MSLS starts from a random "
           f"solution and has to improve it completely. Every local search of ILS also starts close to the best "
           f"solution found so far, whereas MSLS samples local optima independently of each other. Only about "
           f"{accepted['TSPA']:.0f} (TSPA) and {accepted['TSPB']:.0f} (TSPB) of the {num(ils_runs['TSPA'])} / "
           f"{num(ils_runs['TSPB'])} local searches of a run "
           f"({100 * accepted['TSPA'] / ils_runs['TSPA']:.1f} % / {100 * accepted['TSPB'] / ils_runs['TSPB']:.1f} %) "
           f"found a better local optimum, but each of them is cheap.")
    msls_text = (f"<b>MSLS improves on a single local search,</b> from an average of {num(single['TSPA'], 2)} to "
                 f"{num(msls_avg['TSPA'], 2)} on TSPA and from {num(single['TSPB'], 2)} to {num(msls_avg['TSPB'], 2)} on "
                 f"TSPB, but the best of {MSLS_ITERATIONS} random starts is limited by the quality of single local "
                 f"optima: "
                 + ("on TSPA it was " + ("better" if msls_vs_greedy["TSPA"] else "worse") + " than the local search from "
                    f"greedy solutions of assignment 3 ({num(data.avg('TSPA', greedy_ls), 2)}), on TSPB "
                    + ("better" if msls_vs_greedy["TSPB"] else "worse") + f" ({num(data.avg('TSPB', greedy_ls), 2)}).")
                 )
    constructive = (f"<b>Compared with the best construction heuristics,</b> ILS lowered the average objective by "
                    f"{-pct(ils_avg['TSPA'], best_constructive['TSPA']):.1f} % (TSPA) and "
                    f"{-pct(ils_avg['TSPB'], best_constructive['TSPB']):.1f} % (TSPB); it has the lowest average of "
                    f"all methods in Table 1 on both instances.")
    chosen = {i: float(perturbation[i][CHOSEN]["avg"]) for i in INSTANCES}

    def described(perturbation_id: str) -> str:
        return " / ".join(num(float(perturbation[i][perturbation_id]["avg"]), 2) for i in INSTANCES)

    def runs_tspa(perturbation_id: str) -> str:
        return num(float(perturbation["TSPA"][perturbation_id]["ls_runs_average"]))

    components = (f"<b>Both parts of the perturbation are needed.</b> The double bridge alone gave {described('db1')} "
                  f"(TSPA / TSPB) and the segment replacement alone {described('seg4')}, both worse than their "
                  f"combination ({num(chosen['TSPA'], 2)} / {num(chosen['TSPB'], 2)}). The double bridge alone is the "
                  f"cheapest perturbation (about {runs_tspa('db1')} local searches per run on TSPA instead of "
                  f"{runs_tspa(CHOSEN)}), but it does not change which nodes are selected. Ten random moves of the "
                  f"local-search neighbourhood gave {described('random10')}.")
    strength = (f"<b>Stronger perturbations were worse.</b> A segment of 2 or 4 nodes gave about the same results "
                f"({described('db1_seg2')} and {described('db1_seg4')}); a segment of 8 nodes "
                f"({described('db1_seg8')}) or two double bridges ({described('db2_seg4')}) gave worse ones. Such a "
                f"perturbation moves the search further from the current local optimum, and every local search takes "
                f"longer ({runs_tspa('db1_seg8')} and {runs_tspa('db2_seg4')} local searches per run on TSPA instead of "
                f"{runs_tspa(CHOSEN)}).")
    checked = ("All best solutions shown in Section 6 were checked with the provided solution checker (its node data "
               "and formulas, applied to the node lists): every one is a valid solution and the checker objective equals "
               "the reported one." if not problems else
               "The solution checker reported problems: " + "; ".join(esc(p) for p in problems) + ".")
    items = [first, why, msls_text, constructive, components, strength, checked]
    report.page('<h2>7. Conclusions</h2><ul class="conclusions">' + "".join(f"<li>{item}</li>" for item in items) +
                f'</ul><h2>8. Source code</h2><p>The complete source code, the evaluation files and this report '
                f'generator are available at <a href="{REPOSITORY_URL}">{esc(REPOSITORY_URL)}</a>. Build with CMake '
                f'(Release), then run <code>lab06 --seed 20260404 --perturbation-experiment</code> and '
                f'<code>python generate_report.py</code>.</p>')


# ------------------------------------------------------------------------------- styling

CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html { background: #d9d8d3; }
body { margin: 0; font-family: "Segoe UI", system-ui, -apple-system, sans-serif; font-size: 9.6pt; line-height: 1.42;
       color: #0b0b0b; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 210mm; height: 297mm; padding: 15mm 16mm 0; background: #ffffff; position: relative; overflow: hidden;
        break-after: page; margin: 0 auto; }
.content { height: calc(297mm - 15mm - 15mm); overflow: hidden; }
.footer { position: absolute; left: 16mm; right: 16mm; bottom: 7mm; display: flex; justify-content: space-between;
          font-size: 7.5pt; color: #52514e; border-top: 0.5pt solid #e1e0d9; padding-top: 1.8mm; }
h1 { font-size: 20pt; line-height: 1.15; margin: 1mm 0 3mm; font-weight: 650; }
h2 { font-size: 13pt; margin: 5mm 0 2mm; font-weight: 650; }
.content > h2:first-child { margin-top: 0; }
p { margin: 0 0 2.4mm; }
ul, ol { margin: 0 0 2.5mm; padding-left: 5mm; }
li { margin-bottom: 1.2mm; }
a { color: #256abf; text-decoration: none; }
code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 0.92em; white-space: nowrap; }
.nowrap { white-space: nowrap; }
.title { border-bottom: 1.2pt solid #2a78d6; padding-bottom: 4mm; margin-bottom: 5mm; }
.kicker { font-size: 9pt; font-weight: 650; color: #256abf; letter-spacing: 0.04em; text-transform: uppercase; }
.meta { color: #52514e; font-size: 9.4pt; }
.formula { text-align: center; font-size: 11pt; margin: 2.5mm 0; }
pre.code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 7.6pt; line-height: 1.36; background: #f7f7f5;
           border: 0.5pt solid #e1e0d9; border-radius: 2mm; padding: 2.6mm 3.4mm; margin: 0 0 3mm; white-space: pre; }
pre.code .c { color: #52514e; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
caption { caption-side: top; text-align: left; font-weight: 650; padding: 0 0 1.5mm; font-size: 9.2pt; }
table.results { margin: 0 0 5mm; font-size: 8.8pt; }
table.results th, table.results td { border-bottom: 0.5pt solid #e1e0d9; padding: 1.3mm 2mm; text-align: left; }
table.results thead th { background: #f0efec; font-weight: 650; border-bottom: 0.8pt solid #c3c2b7; }
table.results tbody th { font-weight: 600; }
table.results tr.first > * { border-top: 0.9pt solid #c3c2b7; }
table.results td { white-space: nowrap; }
table.results td.num, table.results th.num { text-align: right; }
table.results td.best { font-weight: 700; }
table.times { font-size: 8.4pt; }
.note { font-size: 8.6pt; margin-top: 1.5mm; }
.tablehead { font-weight: 650; font-size: 9.2pt; margin: 0 0 1.5mm; }
svg.figure { width: 100%; height: auto; display: block; margin-bottom: 2mm; }
svg.figure text { font-family: "Segoe UI", system-ui, sans-serif; fill: #0b0b0b; font-variant-numeric: tabular-nums; }
svg.figure text.tick { font-size: 9.5px; fill: #52514e; }
svg.figure text.row { font-size: 10.5px; font-weight: 600; }
svg.figure text.panel { font-size: 11px; font-weight: 650; }
svg.figure text.value { font-size: 9.5px; paint-order: stroke; stroke: #ffffff; stroke-width: 3px; stroke-linejoin: round; }
.legend { font-size: 8.2pt; margin: 0 0 3mm; display: flex; flex-wrap: wrap; align-items: center; gap: 1mm 3.5mm; }
.legend .key { display: inline-flex; align-items: center; gap: 1mm; }
.cards { display: grid; grid-template-columns: 1fr 1fr; gap: 4mm 6mm; }
.card { break-inside: avoid; min-width: 0; }
.cardhead { font-size: 8.6pt; line-height: 1.3; }
.cardhead b { font-weight: 650; }
svg.plot { width: 100%; height: auto; display: block; border: 0.5pt solid #e1e0d9; border-radius: 1mm; background: #ffffff; }
.status { font-size: 7.8pt; margin: 0.2mm 0 1mm; }
.nodes { font-family: "Cascadia Mono", Consolas, monospace; font-size: 6.8pt; line-height: 1.32; word-spacing: 0.25mm;
         margin-top: 1.2mm; }
.bad { color: #d03b3b; font-weight: 700; }
.conclusions li { margin-bottom: 2.2mm; }
@media screen { .page { margin: 0 auto 6mm; } }
"""

OVERFLOW_SCRIPT = """<script>
document.addEventListener('DOMContentLoaded', () => {
  for (const page of document.querySelectorAll('.page')) {
    const content = page.querySelector('.content');
    const extra = content.scrollHeight - content.clientHeight;
    const wide = Math.max(0, ...[...content.querySelectorAll('pre, table, svg')].map(
      element => element.getBoundingClientRect().right - content.getBoundingClientRect().right));
    if (extra > 1) page.setAttribute('data-overflow', String(extra));
    if (wide > 1) page.setAttribute('data-wide', String(Math.round(wide)));
  }
});
</script>"""


# ---------------------------------------------------------------------------- the report

def build_html() -> tuple[str, list[str]]:
    data = Data()
    report = Report()
    first_page(report, data)
    algorithm_pages(report, data)
    results_pages(report, data)
    problems = best_solution_pages(report, data)
    conclusions_page(report, data, problems)
    document = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Lab 06 — MSLS and ILS</title>'
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
    # With a Windows compatibility layer set in the environment (__COMPAT_LAYER, inherited by some
    # shells), headless Edge exits without writing anything, so the browser does not inherit it.
    environment = {key: value for key, value in os.environ.items() if key.upper() != "__COMPAT_LAYER"}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        return subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                               f"--user-data-dir={profile}", *arguments], env=environment,
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
    for attribute, what in (("data-overflow", "content does not fit on"), ("data-wide", "content is too wide on")):
        found = re.findall(rf'<section class="page[^"]*" id="(page-\d+)"[^>]*{attribute}="(\d+)"', dom)
        if found:
            print(f"warning: {what} " + ", ".join(f"{page} (+{extra}px)" for page, extra in found))
    if REPORT_PDF.exists():
        REPORT_PDF.unlink()
    result = run_browser(browser, ["--no-pdf-header-footer", f"--print-to-pdf={REPORT_PDF}", url])
    if not REPORT_PDF.exists():
        sys.exit(f"printing failed: {result.stderr}")
    pages = len(re.findall(rb"/Type\s*/Page[^s]", REPORT_PDF.read_bytes()))
    print(f"wrote {REPORT_PDF} ({pages} pages)")


if __name__ == "__main__":
    main()
