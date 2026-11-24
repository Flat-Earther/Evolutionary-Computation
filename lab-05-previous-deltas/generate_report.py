"""Generate the Lab 05 report (move evaluations from previous iterations) as a PDF.

The report is built as HTML with explicit A4 pages and printed to PDF by a headless
Chromium-based browser (Microsoft Edge or Google Chrome). Inputs are the files written by the
lab05 executable:

    build/lab05.exe --seed 20260404

The plots of the best solutions are the SVG files the executable writes to evaluation/plots.

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
REPOSITORY_URL = "https://github.com/Flat-Earther/Evolutionary-Computation/tree/main/lab-05-previous-deltas"
INSTANCES = ("TSPA", "TSPB")
RUNS = 200
BASELINE, LM_NEW, LM_ALT = "steepest_full", "lm_new_moves", "lm_alternative"
CANDIDATE, LM_CAND = "candidate_k10", "lm_candidate_k10"
METHODS = (BASELINE, LM_NEW, LM_ALT, CANDIDATE, LM_CAND)
LM_METHODS = (LM_NEW, LM_ALT, LM_CAND)
LABELS = {
    BASELINE: "Steepest local search, full neighbourhood (baseline)",
    LM_NEW: "LM — new moves evaluated after each move",
    LM_ALT: "LM — alternative algorithm",
    CANDIDATE: "Candidate moves, K = 10 (assignment 4)",
    LM_CAND: "LM + candidate moves, K = 10",
}
SHORT = {BASELINE: "Baseline", LM_NEW: "LM, new moves", LM_ALT: "LM, alternative", CANDIDATE: "Candidate K = 10",
         LM_CAND: "LM + candidates"}
TABLE_SHORT = {BASELINE: "Baseline", LM_NEW: "LM, new", LM_ALT: "LM, alt.", LM_CAND: "LM + cand."}
CARD_LABELS = {BASELINE: "Full neighbourhood (baseline)", LM_NEW: "LM — new moves after each move",
               LM_ALT: "LM — alternative algorithm", CANDIDATE: "Candidate moves, K = 10",
               LM_CAND: "LM + candidate moves, K = 10"}


# ----------------------------------------------------------------------------------- data

def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        sys.exit(f"missing {path} - run the lab05 experiment first (see the README)")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class Data:
    def __init__(self) -> None:
        self.stats = {i: {r["method_name"]: r for r in read_csv(EVALUATION / f"{i}_stats.csv")} for i in INSTANCES}
        self.times = {i: {r["method_name"]: r for r in read_csv(EVALUATION / f"{i}_times.csv")} for i in INSTANCES}
        self.work = {i: {r["method_name"]: r for r in read_csv(EVALUATION / f"{i}_work.csv")} for i in INSTANCES}
        self.nodes = {i: load_nodes(i) for i in INSTANCES}
        self.checker = load_checker_tables()

    def avg(self, inst: str, method: str) -> float:
        return float(self.stats[inst][method]["avg"])

    def run_ms(self, inst: str, method: str) -> float:
        return float(self.times[inst][method]["average_ms"])

    def speedup(self, inst: str, method: str, reference: str = BASELINE) -> float:
        return self.run_ms(inst, reference) / self.run_ms(inst, method)

    # One-time preparation per instance (not part of a run): candidate lists and LM memory.
    def lists_ms(self, inst: str, method: str) -> float:
        return float(self.times[inst][method]["candidate_lists_ms"])

    def memory_ms(self, inst: str, method: str) -> float:
        return float(self.times[inst][method]["lm_memory_ms"])

    def has_preparation(self, inst: str, method: str) -> bool:
        return self.times[inst][method]["prepared_average_ms"] != ""

    def prepared_run_ms(self, inst: str, method: str) -> float:
        """Average time of a run that does its preparation at its beginning (measured directly);
        for a method without preparation, the time of a run."""
        value = self.times[inst][method]["prepared_average_ms"]
        return float(value) if value != "" else self.run_ms(inst, method)

    def counter(self, inst: str, method: str, name: str) -> float | None:
        value = self.work[inst][method][name]
        return float(value) if value != "" else None

    def full_evaluations(self, inst: str, method: str) -> float:
        # Every iteration of the baseline evaluates the whole neighbourhood once.
        if method == BASELINE:
            return self.counter(inst, method, "applied") + 1
        return self.counter(inst, method, "full_evaluations")


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


def ms(value: float | str) -> str:
    return f"{float(value):.3f}"


def pct(value: float, reference: float) -> float:
    return 100.0 * (value / reference - 1.0)


def signed_pct(value: float, reference: float, decimals: int = 2) -> str:
    return f"{pct(value, reference):+.{decimals}f} %".replace("-", "−")


def share(part: float, whole: float) -> str:
    return f"{100.0 * part / whole:.1f} %"


def same_runs(data: Data, method: str, counter: str = "same_as_baseline") -> str:
    counts = [round(data.counter(inst, method, counter)) for inst in INSTANCES]
    if counts[0] == counts[1]:
        return f"{counts[0]} of {RUNS} runs on both instances"
    return f"{counts[0]} (TSPA) and {counts[1]} (TSPB) of {RUNS} runs"


# ------------------------------------------------------------------------------- figures

def embedded_plot(inst: str, method: str) -> str:
    """The program's plot of the method's best solution (evaluation/plots), inlined. Its small
    title is dropped (the card header repeats it) and the view is cropped to the plotted area."""
    path = EVALUATION / "plots" / f"{inst}_{method}.svg"
    if not path.exists():
        sys.exit(f"missing {path} - run the lab05 experiment first (see the README)")
    svg = re.sub(r"<text\b.*?</text>\s*", "", path.read_text(encoding="utf-8"), flags=re.S)
    opening = (f'<svg class="plot" viewBox="26 26 848 848" role="img" '
               f'aria-label="{esc(f"{inst}: best solution of {LABELS[method]}")}">')
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


# Two series of Figure 1: categorical slots 1 and 2 of the reference palette (validated: light mode on white).
RATIO_SERIES = (("moves evaluated (Δ computed)", "#2a78d6"), ("running time", "#eb6834"))


def bar_path(x0: float, x1: float, y: float, height: float, radius: float = 4.0) -> str:
    """Horizontal bar growing from x0: square at the baseline, rounded data end."""
    r = max(0.0, min(radius, height / 2, x1 - x0))
    return (f"M{x0:.1f},{y:.1f} H{x1 - r:.1f} A{r:.1f},{r:.1f} 0 0 1 {x1:.1f},{y + r:.1f} V{y + height - r:.1f} "
            f"A{r:.1f},{r:.1f} 0 0 1 {x1 - r:.1f},{y + height:.1f} H{x0:.1f} Z")


def ratio_figure(data: Data) -> str:
    """Grouped horizontal bars: deltas computed and running time of the LM methods, both as a
    percentage of the baseline, on one shared axis (baseline = 100 %)."""
    rows = []
    for inst in INSTANCES:
        for method in LM_METHODS:
            rows.append((f"{inst} · {SHORT[method]}",
                         (100 * data.counter(inst, method, "evaluated") / data.counter(inst, BASELINE, "evaluated"),
                          100 * data.run_ms(inst, method) / data.run_ms(inst, BASELINE))))
    width, left, right, top, row_height, bar, gap = 670.0, 150.0, 612.0, 18.0, 31.0, 9.0, 2.0
    height = top + len(rows) * row_height + 24

    def x(percent: float) -> float:
        return left + (right - left) * percent / 100

    parts = [f'<svg class="figure" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="Moves evaluated and '
             f'running time of the LM methods relative to the baseline">']
    bottom = top + len(rows) * row_height
    for tick in (0, 25, 50, 75, 100):
        stroke = "#c3c2b7" if tick == 0 else "#e1e0d9"
        parts.append(f'<line x1="{x(tick):.1f}" y1="{top - 6:.1f}" x2="{x(tick):.1f}" y2="{bottom:.1f}" stroke="{stroke}" '
                     f'stroke-width="1"/>')
        parts.append(f'<text x="{x(tick):.1f}" y="{bottom + 15:.1f}" text-anchor="middle" class="tick">{tick} %</text>')
    parts.append(f'<text x="{x(100):.1f}" y="{top - 9:.1f}" text-anchor="middle" class="tick">baseline</text>')
    for index, (label, values) in enumerate(rows):
        y0 = top + index * row_height + (row_height - 2 * bar - gap) / 2
        parts.append(f'<text x="{left - 10:.1f}" y="{y0 + bar + gap / 2 + 3.6:.1f}" text-anchor="end" class="row">'
                     f'{esc(label)}</text>')
        for series, value in enumerate(values):
            y = y0 + series * (bar + gap)
            parts.append(f'<path d="{bar_path(x(0), x(value), y, bar)}" fill="{RATIO_SERIES[series][1]}"/>')
            parts.append(f'<text x="{x(value) + 5:.1f}" y="{y + bar - 1.0:.1f}" class="value">{value:.1f} %</text>')
    parts.append("</svg>")
    legend = "".join(f'<span class="key"><svg width="14" height="10" viewBox="0 0 14 10"><rect x="0" y="1" width="14" '
                     f'height="8" rx="2" fill="{color}"/></svg>{esc(name)}</span>' for name, color in RATIO_SERIES)
    return f'<div class="legend"><span>Per run, relative to the baseline:</span>{legend}</div>{"".join(parts)}'


# --------------------------------------------------------------------------------- pages

class Report:
    def __init__(self) -> None:
        self.pages: list[str] = []

    def page(self, body: str) -> None:
        number = len(self.pages) + 1
        footer = (f'<div class="footer"><span>Evolutionary Computation · Assignment 5 · Deltas from previous '
                  f'iterations</span><span>{esc(AUTHORS[0][0])}, {esc(AUTHORS[1][0])} · page {number}</span></div>')
        self.pages.append(f'<section class="page" id="page-{number}"><div class="content">{body}</div>{footer}'
                          f'</section>')


def first_page(report: Report) -> None:
    authors = " &nbsp;·&nbsp; ".join(f"{esc(name)} ({esc(index)})" for name, index in AUTHORS)
    report.page(f"""
<div class="title">
  <div class="kicker">Evolutionary Computation · Assignment 5 · Report</div>
  <h1>The use of move evaluations (deltas) from previous iterations in local search</h1>
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
<p>The goal is to make the steepest local search faster by reusing the evaluations of moves (deltas Δ) from previous
iterations. The neighbourhood is the best one of assignment 3: <b>2-opt</b> (exchange of two edges) as the
intra-route move and the <b>exchange</b> of a selected and a not selected node as the inter-route move. Improving
moves of both kinds are kept in one <b>list of moves LM</b>, ordered from the best Δ; a move taken from LM is applied
without being evaluated again. Starting solutions are random. The compared methods are:</p>
<ul>
<li><b>{esc(LABELS[BASELINE])}</b> — evaluates all moves in every iteration, without the mechanisms below.</li>
<li><b>{esc(LABELS[LM_NEW])}</b> — the list of improving moves as presented in the lecture. All moves of the
starting solution are evaluated once; after a move is applied, only the <i>new</i> moves are evaluated (2-opt moves
that remove a new edge, exchanges of a node whose neighbours changed, and exchanges that insert the node that has
just been removed), and the improving ones are added to LM.</li>
<li><b>{esc(LABELS[LM_ALT])}</b> — the alternative algorithm advised in the assignment: no moves are evaluated after
a move is applied; only when LM contains no applicable move are all moves evaluated again.</li>
<li><b>{esc(LABELS[CANDIDATE])}</b> — the steepest local search of assignment 4 restricted to candidate moves (moves
that add at least one candidate edge; candidate edges join a node with its 10 nearest ones, by d(u, v) for 2-opt and
by d(u, v) + c(v) for exchanges), without LM.</li>
<li><b>{esc(LABELS[LM_CAND])}</b> — the optional combination of both mechanisms: LM with new moves after each move,
restricted to the same candidate moves. Only candidate moves are generated — from the candidate lists, for the
starting solution and after every move — so the search applies the same moves as the candidate search of
assignment 4, but computes the Δ of a candidate move only when the move is new or has changed.</li>
</ul>
<p>The pseudocode of all methods is in Section 3, the experimental setup in Section 4, the results in Section 5, the
best solutions with their visualisation and node lists in Section 6 and the conclusions in Section 7.</p>""")


PSEUDOCODE_1 = """<span class="c">Notation</span>
  n nodes, m = ⌈n/2⌉ selected; d(u, v) distance matrix; c(v) node cost
  S  cycle of the selected nodes;  a→b  an edge of S traversed in the direction of S

<b>RANDOM-START</b>()
  P <- random permutation of {0, ..., n-1}             <span class="c">// std::shuffle, mt19937, fixed seed</span>
  return S = (P[0], ..., P[m-1])

<span class="c">Moves: only the change Δ of f is computed, a neighbour solution is never built</span>
  <b>2-OPT</b>(a→b, c→d)      two edges of S without a common node
      remove (a, b), (c, d); add (a, c), (b, d)          <span class="c">// reverses the path b → ... → c</span>
      Δ = d(a, c) + d(b, d) − d(a, b) − d(c, d)
  <b>EXCHANGE</b>(u, v)       u selected, with neighbours p and s in S; v not selected
      v replaces u: remove (p, u), (u, s); add (p, v), (v, s)
      Δ = d(p, v) + d(v, s) + c(v) − d(p, u) − d(u, s) − c(u)

<b>STEEPEST-LOCAL-SEARCH</b>(S)                               <span class="c">// baseline</span>
  repeat
    (move, Δ) <- the best of all 2-OPT and EXCHANGE moves of S
                 <span class="c">// 14 949 moves for n = 200; ties: the first move in a fixed scan order</span>
    if Δ >= 0: return S                                  <span class="c">// local optimum</span>
    apply move to S"""

PSEUDOCODE_2 = """<span class="c">LM: improving moves ordered by Δ, the best first. A stored move consists of nodes only:</span>
<span class="c">  2-opt (a→b, c→d): the removed edges with their directions at evaluation; adds (a, c), (b, d)</span>
<span class="c">  exchange (u, p, s, v): u, between p and s, is replaced by v</span>

<b>CHECK</b>(move, S)                                         <span class="c">// the three situations</span>
  if move = 2-opt (a→b, c→d):
    if {a, b} or {c, d} is not an edge of S:       return REMOVE    <span class="c">// (1) an edge is gone</span>
    if a→b and c→d in S, or b→a and d→c in S:      return APPLY     <span class="c">// (3) same relative direction</span>
    return KEEP                                    <span class="c">// (2) different relative direction</span>
  if move = exchange (u, p, s, v):
    if u is selected between p and s (in either order) and v is not selected:  return APPLY
    return REMOVE

<b>TAKE-BEST</b>(LM, S)
  for move in LM, from the best Δ:
    switch CHECK(move, S):
      REMOVE: delete move from LM
      KEEP:   leave move in LM and continue browsing
      APPLY:  delete move from LM; return move
              <span class="c">// equal Δ: the applicable move that comes first in the baseline's scan order</span>
  return NONE"""

PSEUDOCODE_3 = """<b>ADD-PAIR</b>(LM, a→b, c→d)                <span class="c">// two edges of S without a common node, both reconnections</span>
  Δ1 = d(a, c) + d(b, d) − d(a, b) − d(c, d)
  if Δ1 < 0: insert 2-opt (a→b, c→d) with Δ1 into LM        <span class="c">// applicable now</span>
  Δ2 = d(a, d) + d(b, c) − d(a, b) − d(c, d)
  if Δ2 < 0: insert 2-opt (a→b, d→c) with Δ2 into LM        <span class="c">// relatively inverted edges</span>

<b>ADD-EXCHANGE</b>(LM, u, v)                 <span class="c">// u selected (neighbours p, s), v not selected</span>
  if Δ(EXCHANGE(u, v)) < 0: insert exchange (u, p, s, v) with Δ into LM

<b>EVALUATE-ALL</b>(S, LM)
  for every pair of edges of S without a common node: ADD-PAIR     <span class="c">// m(m−3)/2 pairs, 2 moves each</span>
  for every selected u and not selected v: ADD-EXCHANGE(LM, u, v)   <span class="c">// m(n−m) moves</span>

<b>EVALUATE-NEW</b>(S, LM, move)              <span class="c">// after move has been applied to S</span>
  E <- the two edges added by move;  N <- their end nodes (4 for 2-opt; p, v, s for an exchange)
  for e in E, for every edge f of S without a common node with e: ADD-PAIR(LM, e, f)   <span class="c">// each pair once</span>
  for u in N, for every not selected v: ADD-EXCHANGE(LM, u, v)
  if move was an exchange that removed u: for every selected w not in N: ADD-EXCHANGE(LM, w, u)
  <span class="c">// a pair of two old edges keeps its Δ; whether it can be applied is decided by CHECK</span>

<b>LM-SEARCH</b>(S)                           <span class="c">// new moves evaluated after each move</span>
  LM <- ∅;  EVALUATE-ALL(S, LM)
  loop
    move <- TAKE-BEST(LM, S)
    if move = NONE: return S              <span class="c">// LM holds every improving move: local optimum</span>
    apply move to S;  EVALUATE-NEW(S, LM, move)

<b>LM-ALTERNATIVE</b>(S)                      <span class="c">// the alternative algorithm advised in the assignment</span>
  LM <- ∅;  EVALUATE-ALL(S, LM);  fresh <- true
  loop
    move <- TAKE-BEST(LM, S)
    if move ≠ NONE: apply move to S;  fresh <- false
    else if fresh: return S               <span class="c">// no applicable move right after evaluating all moves</span>
    else: LM <- ∅;  EVALUATE-ALL(S, LM);  fresh <- true"""

PSEUDOCODE_4 = """<span class="c">LM + candidate moves: LM-SEARCH in which EVALUATE-ALL and EVALUATE-NEW consider only candidate moves</span>
<span class="c">C<sub>intra</sub>(u), C<sub>inter</sub>(u): candidate lists of assignment 4 (K = 10), symmetric</span>
<span class="c">A 2-opt move that adds {x, w} removes one edge at x and one edge at w, so there are 4 of them:</span>

<b>ADD-MOVES-WITH</b>(LM, x, w)               <span class="c">// {x, w} is an intra candidate edge, x and w are selected</span>
  for e in {x→succ(x), pred(x)→x} and f in {w→succ(w), pred(w)→w}, e and f without a common node:
    if x and w are both tails or both heads of e and f: add the reconnection of e, f applicable now
    else: add the reconnection of e, f with relatively inverted edges         <span class="c">// each one adds {x, w}</span>
                                          <span class="c">// "add": insert into LM if its Δ < 0; a move is added only once</span>

<b>EVALUATE-ALL-C</b>(S, LM)
  for every candidate edge {x, w} between selected nodes: ADD-MOVES-WITH(LM, x, w)
  for every position i, every not selected v in C<sub>inter</sub>(S[i−1]) ∪ C<sub>inter</sub>(S[i+1]): ADD-EXCHANGE(LM, S[i], v)

<b>EVALUATE-NEW-C</b>(S, LM, move)            <span class="c">// E and N as in EVALUATE-NEW</span>
  for e = x→y in E, every selected w in C<sub>intra</sub>(x) ∪ C<sub>intra</sub>(y):
    add the moves of ADD-MOVES-WITH(LM, x, w) or (LM, y, w) that remove e
  for u in N, every not selected v in C<sub>inter</sub>(pred(u)) ∪ C<sub>inter</sub>(succ(u)): ADD-EXCHANGE(LM, u, v)
  if move was an exchange that removed u: ADD-EXCHANGE(LM, t, u) for every selected t next to a node of C<sub>inter</sub>(u)

<span class="c">An exchange entering v next to a node a has Δ >= d(a, v) + c(v) − (length and cost it removes), so the lists</span>
<span class="c">C<sub>inter</sub> are sorted by d(a, v) + c(v) and a scan stops as soon as this bound is >= 0: no improving move is lost</span>"""


def algorithm_pages(report: Report) -> None:
    report.page(f"""
<h2>2.1 Moves stored in LM</h2>
<p>A stored move keeps only node indices — a 2-opt move the two edges it removes, with their directions at
evaluation; an exchange the removed node, its two neighbours and the inserted node — so its Δ stays valid as long as
the move can be applied. When LM is browsed, a stored 2-opt move is <b>(1) removed</b> if one of its edges no longer
exists, <b>(2) kept but skipped</b> if both edges exist in a different relative direction (it may become applicable
later), and <b>(3) applied</b> and removed if both exist in the same relative direction (also both reversed). An
exchange is applied if the removed node still lies between the same two neighbours and the inserted node is still
not selected, and removed otherwise. Every pair of edges is evaluated in <b>both reconnections</b> — the one
applicable now and the one with relatively inverted edges, which becomes applicable after another move reverses one
of the edges — also when the starting solution is evaluated.</p>
<h2>3. Algorithms (pseudocode)</h2>
<p>All methods are steepest local searches; they differ in how the best improving move is found in every iteration and
in the neighbourhood that is searched (complete, or candidate moves only).</p>
<pre class="code">{PSEUDOCODE_1}</pre>
<pre class="code">{PSEUDOCODE_2}</pre>""")
    report.page(f"""
<pre class="code">{PSEUDOCODE_3}</pre>
<p class="note">The assignment's version of the alternative algorithm stops when LM is empty. Moves of situation (2)
remain in LM while they are not applicable, so LM need not be empty at a local optimum; the search therefore stops
when an evaluation of all moves gives no applicable move, which means that S is a local optimum. LM is cleared before
every such evaluation, so no move is stored twice.</p>
<pre class="code">{PSEUDOCODE_4}</pre>""")
    report.page(f"""
<h2>3.1 Implementation</h2>
<ul>
<li><b>LM as a bucket queue.</b> Δ is an integer between −(2·max d + max c) and −1, so LM is an array of buckets
indexed by −Δ, each a linked list of moves, with a bit mask of the non-empty buckets. Inserting a move takes constant
time and browsing visits the moves in the order of Δ without any sorting. A stored move takes 16 bytes (four node
indices, type, link); its Δ is given by the bucket.</li>
<li><b>Checks in constant time.</b> The successor of every node is kept in an array (−1 for nodes that are not
selected): x→y is an edge of S exactly when succ(x) = y. Both kinds of moves are checked without branching on the
move type.</li>
<li><b>Ties.</b> Among the applicable moves with the best Δ, the one that comes first in the scan order of the
reference search is applied (its rank is computed from the node positions): the baseline for LM on the full
neighbourhood, the candidate search of assignment 4 for LM + candidate moves. Both searches therefore apply exactly
the same moves as their reference and reach the same local optimum from every starting solution.</li>
<li><b>Evaluation.</b> The route has sentinel copies of its ends and the lengths of its edges are cached. Scans write
every move into a buffer and keep only the improving ones without branches; the exchange scans run over whole rows of
the distance matrix, four nodes at a time (SSE2), with a prohibitive insertion cost for selected nodes. LM + candidate
moves uses the candidate lists built by the solver of assignment 4, so both methods have identical lists.</li>
<li><b>Memory.</b> LM (the buckets and a pool of moves) is allocated once per instance and reused by all runs.</li>
<li><b>Verification.</b> After every run the objective is recomputed from scratch and compared with the sum of the
applied deltas, and the result is checked to be a local optimum of the neighbourhood that was searched.</li>
<li><b>Baseline and candidate moves</b> use the implementation of assignment 4: the full neighbourhood is evaluated
row by row, each row reduced to its minimum without branches (vectorised by the compiler).</li>
</ul>{experiment_text()}""")


def experiment_text() -> str:
    return """
<h2>4. Computational experiment</h2>
<ul>
<li><b>Runs.</b> Every method was run 200 times on each instance, always from the same 200 random starting solutions
(seed 20260404 combined with an instance-specific constant — the same starting solutions as in assignment 4). Every
run continues until a local optimum is reached.</li>
<li><b>Running time</b> is the wall-clock time of one local-search run, from the starting solution to the local
optimum. Every run was timed 5 times from the same starting solution, interleaved with the runs of the other methods
(for every starting solution, every method once), so changes of the processor clock affect all methods alike; the
smallest of the 5 times counts, which suppresses interruptions by the operating system. Table 2 gives the average
(minimum – maximum) of these times over the 200 starting solutions.</li>
<li><b>Preparation</b> is done once per instance and is not part of a run: building the candidate lists (K = 10) and
creating LM (finding the range of Δ, allocating and initialising its memory; for LM + candidate moves also copying the
candidate lists). Its time was measured separately, as the median over all starting solutions and repetitions. In
addition, every method with a preparation was timed with all of it done at the beginning of every run, in the same
way as the normal runs (Table 3).</li>
<li><b>Environment.</b> AMD Ryzen 7 7840HS, Windows 11; GCC 16.2 (MSYS2 UCRT64), CMake Release build
(<span class="nowrap">-O3 -march=x86-64-v2</span>), single thread.</li>
</ul>"""


def results_page(report: Report, data: Data) -> None:
    best_avg = {i: min(data.avg(i, m) for m in METHODS) for i in INSTANCES}
    best_time = {i: min(data.run_ms(i, m) for m in METHODS) for i in INSTANCES}
    score_rows, time_rows, preparation_rows = [], [], []
    for method in METHODS:
        cells = []
        for inst in INSTANCES:
            row = data.stats[inst][method]
            cls = ' class="best"' if data.avg(inst, method) == best_avg[inst] else ""
            cells.append(f"<td{cls}>{float(row['avg']):.2f} ({float(row['min']):.0f} – {float(row['max']):.0f})</td>")
        score_rows.append(f"<tr><th>{esc(LABELS[method])}</th>{''.join(cells)}</tr>")
        cells = []
        for inst in INSTANCES:
            row = data.times[inst][method]
            cls = ' class="best"' if data.run_ms(inst, method) == best_time[inst] else ""
            factor = "—" if method == BASELINE else f"{data.speedup(inst, method):.2f}×"
            cells.append(f"<td{cls}>{ms(row['average_ms'])} ({ms(row['minimum_ms'])} – {ms(row['maximum_ms'])})</td>"
                         f"<td class=\"num\">{factor}</td>")
        time_rows.append(f"<tr><th>{esc(LABELS[method])}</th>{''.join(cells)}</tr>")
        if data.has_preparation(INSTANCES[0], method):
            cells = []
            for inst in INSTANCES:
                lists = data.lists_ms(inst, method)
                memory = data.memory_ms(inst, method)
                cells.append(f'<td class="num">{ms(lists) if lists > 0 else "—"}</td>'
                             f'<td class="num">{ms(memory) if memory > 0 else "—"}</td>'
                             f'<td class="num">{ms(data.prepared_run_ms(inst, method))}</td>')
            preparation_rows.append(f"<tr><th>{esc(LABELS[method])}</th>{''.join(cells)}</tr>")
    baseline = "".join(f'<td class="num">—</td><td class="num">—</td><td class="num">{ms(data.run_ms(i, BASELINE))}</td>'
                       for i in INSTANCES)
    preparation_rows.insert(0, f"<tr><th>{esc(LABELS[BASELINE])}</th>{baseline}</tr>")
    cand_speed = "/".join(f"{data.speedup(i, LM_CAND, CANDIDATE):.2f}×" for i in INSTANCES)
    report.page(f"""
<h2>5. Results</h2>
<table class="results">
<caption>Table 1. Objective function: average (minimum – maximum) over 200 runs; the lowest average in bold</caption>
<thead><tr><th>Method</th><th>TSPA</th><th>TSPB</th></tr></thead>
<tbody>{''.join(score_rows)}</tbody></table>
<table class="results times">
<caption>Table 2. Running time of one local-search run in ms: average (minimum – maximum); speed-up = average time of
the baseline / average time of the method; the lowest average in bold</caption>
<thead><tr><th rowspan="2">Method</th><th colspan="2">TSPA</th><th colspan="2">TSPB</th></tr>
<tr><th>time</th><th>speed-up</th><th>time</th><th>speed-up</th></tr></thead>
<tbody>{''.join(time_rows)}</tbody></table>
<table class="results times prep">
<caption>Table 3. One-time preparation per instance in ms (median of repeated measurements, not included in Table 2),
and the average time of a run that does all of its preparation at its beginning (measured directly)</caption>
<thead><tr><th rowspan="2">Method</th><th colspan="3">TSPA</th><th colspan="3">TSPB</th></tr>
<tr><th>candidate lists</th><th>LM memory</th><th>run incl. preparation</th><th>candidate lists</th><th>LM memory</th>
<th>run incl. preparation</th></tr></thead>
<tbody>{''.join(preparation_rows)}</tbody></table>
<p class="note">Runs that ended in exactly the same local optimum: LM with new moves as the baseline —
{same_runs(data, LM_NEW)}; the alternative algorithm as the baseline — {same_runs(data, LM_ALT)}; LM + candidate moves
as candidate moves — {same_runs(data, LM_CAND, "same_as_candidate")}. LM + candidate moves was {cand_speed} (TSPA/TSPB)
faster than candidate moves. The memory of LM is allocated once per instance and reused by all runs, so it is not
part of the run times in Table 2; Table 3 gives its cost.</p>""")


def work_page(report: Report, data: Data) -> None:
    methods = (BASELINE, LM_NEW, LM_ALT, LM_CAND)

    def cell(inst: str, method: str, name: str, decimals: int = 0) -> str:
        value = data.counter(inst, method, name)
        return "—" if value is None else num(value, decimals)

    def evaluations(inst: str, method: str) -> str:
        return num(data.full_evaluations(inst, method), 1)

    rows = [
        ("Moves applied", lambda i, m: cell(i, m, "applied", 1)),
        ("… of which 2-opt", lambda i, m: cell(i, m, "applied_two_opt", 1)),
        ("… … with relatively inverted edges", lambda i, m: cell(i, m, "applied_inverted", 1)),
        ("Moves evaluated (Δ computed)", lambda i, m: cell(i, m, "evaluated")),
        ("Evaluations of all moves", evaluations),
        ("Moves inserted into LM", lambda i, m: cell(i, m, "inserted")),
        ("… by evaluating the starting solution", lambda i, m: cell(i, m, "initial_inserted")),
        ("Moves checked while browsing LM", lambda i, m: cell(i, m, "checked")),
        ("… removed: edge or node gone (1)", lambda i, m: cell(i, m, "removed")),
        ("… kept: other relative direction (2)", lambda i, m: cell(i, m, "not_applicable")),
    ]
    head = "".join(f'<th colspan="{len(methods)}">{inst}</th>' for inst in INSTANCES)
    sub = "".join(f"<th>{esc(TABLE_SHORT[m])}</th>" for _ in INSTANCES for m in methods)
    body = []
    for label, getter in rows:
        cells = "".join(f'<td class="num">{getter(inst, method)}</td>' for inst in INSTANCES for method in methods)
        body.append(f"<tr><th>{esc(label)}</th>{cells}</tr>")
    table = (f'<table class="results work"><caption>Table 4. Work per run (averages over 200 runs). For the baseline, '
             f'every iteration is one evaluation of all moves ({num(14949)} moves); for LM + candidate moves, an evaluation '
             f'of all moves means all candidate moves.</caption><thead><tr><th rowspan="2">'
             f'</th>{head}</tr><tr>{sub}</tr></thead><tbody>{"".join(body)}</tbody></table>')

    def outcomes(inst: str, method: str) -> str:
        checked, removed = data.counter(inst, method, "checked"), data.counter(inst, method, "removed")
        kept = data.counter(inst, method, "not_applicable")
        return (f"{share(removed, checked)} removed, {share(kept, checked)} kept, "
                f"{share(checked - removed - kept, checked)} applicable")

    notes = (f"Outcome of the checks of LM with new moves: {outcomes('TSPA', LM_NEW)} (TSPA); "
             f"{outcomes('TSPB', LM_NEW)} (TSPB). The applicable moves include the moves applied and, rarely, moves "
             f"with the same Δ as the applied one that come later in the scan order.")
    report.page(f"""{table}<p class="note">{notes}</p>
<div class="tablehead figurehead">Figure 1. Moves evaluated and running time of the LM methods, as a percentage of the
baseline (averages per run; the values are in Tables 2 and 4)</div>
{ratio_figure(data)}""")


def best_solution_pages(report: Report, data: Data) -> list[str]:
    """The program's plot of the best solution of every method, its node list and a check with the
    solution checker's data and formulas. Returns a description of every problem found (expected: none)."""
    problems = []
    for inst in INSTANCES:
        routes = {method: read_route(inst, method) for method in METHODS}
        rendered = []
        for method in METHODS:
            route = routes[method]
            reported = round(float(data.stats[inst][method]["min"]))
            checked = checker_objective(data.checker[inst], route)
            if checked is None:
                status = '<span class="bad">not a valid solution</span>'
                problems.append(f"{inst} {method}: not a valid solution")
            elif checked == reported:
                status = f"f = {reported} · checker {checked} ✓"
            else:
                status = f'<span class="bad">f = {reported}, checker {checked} ≠ {reported}</span>'
                problems.append(f"{inst} {method}: checker {checked} != reported {reported}")
            rendered.append(f'<div class="card"><div class="cardhead"><b>{esc(CARD_LABELS[method])}</b></div>'
                            f'<div class="status">{status}</div>{embedded_plot(inst, method)}'
                            f'<div class="nodes">{" ".join(str(node) for node in route)}</div></div>')
        same = []
        if routes[BASELINE] == routes[LM_NEW]:
            same.append("the best solutions of the baseline and of LM with new moves are identical")
        if routes[CANDIDATE] == routes[LM_CAND]:
            same.append("those of candidate moves and of LM + candidate moves are identical")
        note = ""
        if same:
            sentence = " and ".join(same)
            note = f" {sentence[0].upper()}{sentence[1:]}, because these methods reach the same local optimum from every " \
                   f"starting solution."
        report.page(f"<h2>6. Best solutions — {inst}</h2><p>The best solution of every method (the lowest objective in "
                    f"200 runs), as plotted by the program, with its objective f, the result of the solution checker and "
                    f"the node list. Node indices start from 0; the cycle returns from the last listed node to the first."
                    f"{note}</p>{plot_legend(data.nodes[inst])}<div class=\"cards\">{''.join(rendered)}</div>")
    return problems


def conclusions_page(report: Report, data: Data, problems: list[str]) -> None:
    speed_new = {i: data.speedup(i, LM_NEW) for i in INSTANCES}
    speed_alt = {i: data.speedup(i, LM_ALT) for i in INSTANCES}
    fewer = {i: data.counter(i, BASELINE, "evaluated") / data.counter(i, LM_NEW, "evaluated") for i in INSTANCES}
    removed = {i: data.counter(i, LM_NEW, "removed") / data.counter(i, LM_NEW, "checked") for i in INSTANCES}
    kept = {i: data.counter(i, LM_NEW, "not_applicable") / data.counter(i, LM_NEW, "checked") for i in INSTANCES}
    inverted = {i: data.counter(i, LM_NEW, "applied_inverted") / data.counter(i, LM_NEW, "applied_two_opt")
                for i in INSTANCES}
    same_new = all(data.counter(i, LM_NEW, "same_as_baseline") == RUNS for i in INSTANCES)
    same_cand = all(data.counter(i, LM_CAND, "same_as_candidate") == RUNS for i in INSTANCES)
    alt_faster = all(data.run_ms(i, LM_ALT) < data.run_ms(i, LM_NEW) for i in INSTANCES)
    alt_more_evaluated = all(data.counter(i, LM_ALT, "evaluated") > data.counter(i, LM_NEW, "evaluated")
                             for i in INSTANCES)
    lm_beats_candidate = all(max(data.run_ms(i, LM_NEW), data.run_ms(i, LM_ALT)) < data.run_ms(i, CANDIDATE)
                             for i in INSTANCES)
    fastest = all(data.run_ms(i, LM_CAND) == min(data.run_ms(i, m) for m in METHODS) for i in INSTANCES)

    first = (f"<b>Reusing move evaluations makes the steepest local search faster without changing it.</b> "
             + ("LM with new moves reached exactly the same local optimum as the baseline in all 200 runs on both "
                "instances, with the same average number of applied moves (Table 4), " if same_new else
                "LM with new moves reached the baseline's quality, ")
             + f"while one run took {ms(data.run_ms('TSPA', LM_NEW))} instead of {ms(data.run_ms('TSPA', BASELINE))} ms "
               f"on TSPA ({speed_new['TSPA']:.2f}× faster) and {ms(data.run_ms('TSPB', LM_NEW))} instead of "
               f"{ms(data.run_ms('TSPB', BASELINE))} ms on TSPB ({speed_new['TSPB']:.2f}×).")
    n = len(data.nodes["TSPA"])
    m = (n + 1) // 2
    all_moves = m * (m - 3) + m * (n - m)  # both reconnections of every pair of edges, every exchange
    initial = data.counter("TSPA", LM_NEW, "initial_inserted")
    work = (f"<b>The speed-up is much smaller than the saving in evaluations.</b> LM with new moves computed "
            f"{fewer['TSPA']:.0f}× (TSPA) and {fewer['TSPB']:.0f}× (TSPB) fewer deltas than the baseline, but every "
            f"improving move must be inserted into LM and checked later — "
            f"{num(data.counter('TSPA', LM_NEW, 'inserted'))} insertions and "
            f"{num(data.counter('TSPA', LM_NEW, 'checked'))} checks per run on TSPA — and the new moves are scattered "
            f"over the solution, while the baseline evaluates whole rows of moves in regular, vectorised loops. A random "
            f"starting solution is far from a local optimum: {num(initial)} of its {num(all_moves)} evaluated moves "
            f"({share(initial, all_moves)}) were improving and entered LM. Of all moves inserted into LM, "
            f"{share(data.counter('TSPA', LM_NEW, 'removed'), data.counter('TSPA', LM_NEW, 'inserted'))} (TSPA) were "
            f"later removed because an edge or node was gone — evaluated, inserted and checked without ever being "
            f"applied.")
    situations = (f"<b>Most stored moves become invalid.</b> {100 * removed['TSPA']:.1f} % (TSPA) and "
                  f"{100 * removed['TSPB']:.1f} % (TSPB) of the moves checked in LM were removed because an edge or node "
                  f"was gone, and {100 * kept['TSPA']:.1f} % / {100 * kept['TSPB']:.1f} % were kept because their edges "
                  f"had a different relative direction. Removing invalid moves lazily, only when browsing reaches them, "
                  f"costs one check per move and needs no search for the moves affected by a change.")
    inverted_text = (f"<b>Moves with relatively inverted edges matter.</b> {100 * inverted['TSPA']:.0f} % (TSPA) and "
                     f"{100 * inverted['TSPB']:.0f} % (TSPB) of the 2-opt moves applied by LM with new moves had been "
                     f"evaluated with relatively inverted edges and became applicable only after another move reversed "
                     f"one of their edges. Without evaluating them, LM would miss these improving moves and the search "
                     f"would no longer be the steepest one.")
    alt_quality = (f"{signed_pct(data.avg('TSPA', LM_ALT), data.avg('TSPA', BASELINE))} (TSPA) and "
                   f"{signed_pct(data.avg('TSPB', LM_ALT), data.avg('TSPB', BASELINE))} (TSPB)")
    alternative = (f"<b>The alternative algorithm</b> was {speed_alt['TSPA']:.2f}× (TSPA) and {speed_alt['TSPB']:.2f}× "
                   f"(TSPB) faster than the baseline"
                   + (", even faster than LM with new moves although it evaluated more moves "
                      f"({num(data.counter('TSPA', LM_ALT, 'evaluated'))} vs. {num(data.counter('TSPA', LM_NEW, 'evaluated'))} "
                      "on TSPA): it evaluates all moves in regular scans, about "
                      f"{data.full_evaluations('TSPA', LM_ALT):.0f} times per run, and inserts and checks fewer moves."
                      if alt_faster and alt_more_evaluated else ".")
                   + f" It applies stored moves in the order of their old Δ and ignores the moves created in the "
                     f"meantime, so it does not follow the steepest path: it applied more moves "
                     f"({data.counter('TSPA', LM_ALT, 'applied'):.0f} vs. {data.counter('TSPA', LM_NEW, 'applied'):.0f} "
                     f"on TSPA) and ended in other local optima, of the same average quality ({alt_quality} vs. the "
                     f"baseline).")
    cand_quality = (f"{signed_pct(data.avg('TSPA', LM_CAND), data.avg('TSPA', BASELINE))} (TSPA) and "
                    f"{signed_pct(data.avg('TSPB', LM_CAND), data.avg('TSPB', BASELINE))} (TSPB)")
    cand_fewer = data.counter("TSPA", LM_NEW, "evaluated") / data.counter("TSPA", LM_CAND, "evaluated")
    combination = (f"<b>Combining LM with candidate moves</b> "
                   + ("gave the fastest search on both instances. " if fastest else "also works. ")
                   + ("It reached exactly the same local optimum as candidate moves of assignment 4 in all 200 runs on "
                      "both instances, so it applies the same moves, but computes a Δ only when a move is new or has changed: "
                      if same_cand else "")
                   + f"one run took {ms(data.run_ms('TSPA', LM_CAND))} instead of {ms(data.run_ms('TSPA', CANDIDATE))} ms "
                     f"on TSPA ({data.speedup('TSPA', LM_CAND, CANDIDATE):.2f}× faster) and "
                     f"{ms(data.run_ms('TSPB', LM_CAND))} instead of {ms(data.run_ms('TSPB', CANDIDATE))} ms on TSPB "
                     f"({data.speedup('TSPB', LM_CAND, CANDIDATE):.2f}×). It computed {cand_fewer:.0f}× fewer deltas than LM "
                     f"with the full neighbourhood (on TSPA), but was only "
                     f"{data.speedup('TSPA', LM_CAND, LM_NEW):.2f}× faster, because candidate moves are generated from lists "
                     f"with irregular memory accesses and branches instead of regular scans. The average quality is that "
                     f"of candidate moves: {cand_quality} compared with the full neighbourhood.")
    full_lm = (f"<b>LM on the full neighbourhood does not restrict the search.</b> "
               + ("Both LM variants were faster than candidate moves (K = 10, without LM) on both instances, and "
                  if lm_beats_candidate else "")
               + "LM with new moves keeps exactly the quality of the full neighbourhood, while candidate moves changed "
                 f"the average by {signed_pct(data.avg('TSPA', CANDIDATE), data.avg('TSPA', BASELINE))} (TSPA) and "
                 f"{signed_pct(data.avg('TSPB', CANDIDATE), data.avg('TSPB', BASELINE))} (TSPB).")
    memory_new = " / ".join(ms(data.memory_ms(i, LM_NEW)) for i in INSTANCES)
    memory_cand = " / ".join(ms(data.memory_ms(i, LM_CAND)) for i in INSTANCES)
    lists = " / ".join(ms(data.lists_ms(i, LM_CAND)) for i in INSTANCES)
    still_faster = all(data.prepared_run_ms(i, LM_NEW) < data.run_ms(i, BASELINE) for i in INSTANCES)
    cand_slower = all(data.prepared_run_ms(i, LM_CAND) > data.run_ms(i, BASELINE) for i in INSTANCES)
    preparation = (f"<b>Preparation must be reused.</b> Creating LM takes {memory_new} ms (TSPA / TSPB), and {memory_cand} "
                   f"ms for LM + candidate moves, which also copies the candidate lists; building these lists takes {lists} "
                   f"ms, as long as "
                   f"{data.lists_ms('TSPA', LM_CAND) / data.run_ms('TSPA', LM_CAND):.1f} / "
                   f"{data.lists_ms('TSPB', LM_CAND) / data.run_ms('TSPB', LM_CAND):.1f} runs of LM + candidate moves. Done "
                   f"once per instance, this is negligible over {RUNS} runs. A run that does all of its preparation at its "
                   f"beginning took {ms(data.prepared_run_ms('TSPA', LM_NEW))} / "
                   f"{ms(data.prepared_run_ms('TSPB', LM_NEW))} ms for LM with new moves (TSPA / TSPB), "
                   + ("still faster than the baseline" if still_faster else "slower than the baseline")
                   + (f", and {ms(data.prepared_run_ms('TSPA', LM_CAND))} / {ms(data.prepared_run_ms('TSPB', LM_CAND))} ms for "
                      f"LM + candidate moves, slower than the baseline." if cand_slower else "."))
    checked = ("All best solutions shown in Section 6 were checked with the provided solution checker (its node data "
               "and formulas, applied to the node lists): every one is a valid solution and the checker objective equals "
               "the reported one." if not problems else
               "The solution checker reported problems: " + "; ".join(esc(p) for p in problems) + ".")
    items = [first, work, situations, inverted_text, alternative, combination, full_lm, preparation, checked]
    report.page('<h2>7. Conclusions</h2><ul class="conclusions">' + "".join(f"<li>{item}</li>" for item in items) +
                f'</ul><h2>8. Source code</h2><p>The complete source code, the evaluation files and this report '
                f'generator are available at <a href="{REPOSITORY_URL}">{esc(REPOSITORY_URL)}</a>. Build with CMake '
                f'(Release), then run <code>lab05 --seed 20260404</code> and <code>python generate_report.py</code>.</p>')


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
pre.code { font-family: "Cascadia Mono", Consolas, monospace; font-size: 7.4pt; line-height: 1.34; background: #f7f7f5;
           border: 0.5pt solid #e1e0d9; border-radius: 2mm; padding: 2.4mm 3.2mm; margin: 0 0 3mm; white-space: pre; }
pre.code .c { color: #52514e; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
caption { caption-side: top; text-align: left; font-weight: 650; padding: 0 0 1.5mm; font-size: 9.2pt; }
table.results { margin: 0 0 4.5mm; font-size: 8.8pt; }
table.results th, table.results td { border-bottom: 0.5pt solid #e1e0d9; padding: 1.2mm 1.8mm; text-align: left; }
table.results thead th { background: #f0efec; font-weight: 650; border-bottom: 0.8pt solid #c3c2b7; }
table.results tbody th { font-weight: 600; }
table.results td { white-space: nowrap; }
table.results td.num { text-align: right; }
table.results td.best { font-weight: 700; }
table.times { font-size: 8.4pt; }
table.prep thead tr:last-child th { text-align: right; }
table.work { font-size: 7.6pt; }
table.work thead th { text-align: right; }
table.work thead tr:first-child th { text-align: center; }
table.work tbody th { font-weight: 500; width: 27%; }
table.work td, table.work tbody th { padding-left: 0.9mm; padding-right: 0.9mm; }
.note { font-size: 8.6pt; margin-top: 1.5mm; }
.tablehead { font-weight: 650; font-size: 9.2pt; margin: 0 0 1.5mm; }
.figurehead { margin-top: 6mm; }
svg.figure { width: 100%; height: auto; display: block; }
svg.figure text { font-family: "Segoe UI", system-ui, sans-serif; fill: #0b0b0b; font-variant-numeric: tabular-nums; }
svg.figure text.tick { font-size: 9.5px; fill: #52514e; }
svg.figure text.row { font-size: 10.5px; }
svg.figure text.value { font-size: 9.5px; paint-order: stroke; stroke: #ffffff; stroke-width: 3px; stroke-linejoin: round; }
.legend { font-size: 8.2pt; margin: 0 0 3mm; display: flex; flex-wrap: wrap; align-items: center; gap: 1mm 3.5mm; }
.legend .key { display: inline-flex; align-items: center; gap: 1mm; }
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4mm 5mm; }
.card { break-inside: avoid; min-width: 0; }
.cardhead { font-size: 8.2pt; line-height: 1.3; }
.cardhead b { font-weight: 650; }
svg.plot { width: 100%; height: auto; display: block; border: 0.5pt solid #e1e0d9; border-radius: 1mm; background: #ffffff; }
.status { font-size: 7.6pt; margin: 0.2mm 0 1mm; }
.nodes { font-family: "Cascadia Mono", Consolas, monospace; font-size: 6.1pt; line-height: 1.3; word-spacing: 0.2mm;
         margin-top: 1mm; }
.bad { color: #d03b3b; font-weight: 700; }
.conclusions li { margin-bottom: 2.0mm; }
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
    first_page(report)
    algorithm_pages(report)
    results_page(report, data)
    work_page(report, data)
    problems = best_solution_pages(report, data)
    conclusions_page(report, data, problems)
    document = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Lab 05 — Deltas from previous '
                f'iterations</title><style>{CSS}</style></head><body>{"".join(report.pages)}{OVERFLOW_SCRIPT}'
                f'</body></html>')
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
