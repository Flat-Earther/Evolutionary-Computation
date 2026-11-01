"""Generate the Lab 03 local-search report and compare all course methods."""

from __future__ import annotations

import base64
import csv
import html
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVALUATION = ROOT / "evaluation"
LAB01_EVALUATION = ROOT.parent / "lab-01-greedy-heuristics" / "evaluation"
LAB02_EVALUATION = ROOT.parent / "lab-02-greedy-regret-heuristics" / "evaluation"
REPORT = ROOT / "report.pdf"
BUILD = ROOT / ".report-build"
WIDTH = 1240
HEIGHT = 1754

NAVY = "#12243a"
BLUE = "#1f5f8b"
TEAL = "#2c8c87"
ORANGE = "#e98b45"
INK = "#1e2936"
MUTED = "#607080"
LIGHT = "#f4f7fa"
PALE_BLUE = "#e8f1f7"
PALE_TEAL = "#e9f5f2"
PALE_ORANGE = "#fff1e6"
GRID = "#d8e1e8"
WHITE = "#ffffff"

AUTHOR_ONE = "Pawe" + chr(0x142) + " " + chr(0x15a) + "wi" + chr(0x105) + "tek"
AUTHOR_TWO = "J" + chr(0x119) + "drzej Szmidt"
REPOSITORY_URL = "https://github.com/Flat-Earther/Evolutionary-Computation/tree/main/lab-03-local-search"

BASELINE_METHODS = [
    ("random_sol", "Random solution", "random_sol", "lab01"),
    ("nn_at_end", "Nearest neighbor - end", "nn_at_end", "lab01"),
    ("nn_flexible", "Nearest neighbor - any position", "nn_flexible", "lab01"),
    ("greedy_cycle", "Greedy cycle", "greedy_cycle", "lab01"),
]
REGRET_METHODS = [
    ("regret2_path", "2-regret - path", "regret2_path", "lab02"),
    ("regret2_cycle", "2-regret - cycle", "regret2_cycle", "lab02"),
    ("weighted_path", "Weighted regret - path", "weighted_path", "lab02"),
    ("weighted_cycle", "Weighted regret - cycle", "weighted_cycle", "lab02"),
]
LOCAL_METHODS = [
    ("random_steepest_node", "Random / steepest / node exchange", "random_steepest_node", "lab03"),
    ("random_steepest_2opt", "Random / steepest / 2-opt", "random_steepest_2opt", "lab03"),
    ("random_greedy_node", "Random / greedy / node exchange", "random_greedy_node", "lab03"),
    ("random_greedy_2opt", "Random / greedy / 2-opt", "random_greedy_2opt", "lab03"),
    ("greedy_steepest_node", "Best greedy / steepest / node exchange", "greedy_steepest_node", "lab03"),
    ("greedy_steepest_2opt", "Best greedy / steepest / 2-opt", "greedy_steepest_2opt", "lab03"),
    ("greedy_greedy_node", "Best greedy / greedy / node exchange", "greedy_greedy_node", "lab03"),
    ("greedy_greedy_2opt", "Best greedy / greedy / 2-opt", "greedy_greedy_2opt", "lab03"),
]
ALL_METHODS = BASELINE_METHODS + REGRET_METHODS + LOCAL_METHODS


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def fmt(value: str | float | int, places: int = 2) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{places}f}"


def fmt_average(value: str | float | int) -> str:
    return f"{float(value):.2f}"


def wrap(value: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in value.split():
        candidate = word if not current else f"{current} {word}"
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def text(x: float, y: float, value: str, size: int = 20, fill: str = INK,
         weight: str = "400", family: str = "Arial", anchor: str = "start") -> str:
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}px" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{esc(value)}</text>')


def multiline(x: float, y: float, lines: list[str], size: int = 20, fill: str = INK,
              weight: str = "400", family: str = "Arial", line_height: int | None = None) -> str:
    line_height = line_height or int(size * 1.35)
    tspans = []
    for index, line in enumerate(lines):
        dy = 0 if index == 0 else line_height
        tspans.append(f'<tspan x="{x}" dy="{dy}">{esc(line)}</tspan>')
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}px" '
            f'font-weight="{weight}" fill="{fill}">' + "".join(tspans) + "</text>")


def rect(x: float, y: float, width: float, height: float, fill: str = WHITE,
         stroke: str = "none", radius: int = 18, stroke_width: int = 1,
         opacity: float = 1.0) -> str:
    return (f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" opacity="{opacity}"/>')


def line(x1: float, y1: float, x2: float, y2: float, stroke: str = GRID, width: int = 1) -> str:
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}"/>'


def circle(cx: float, cy: float, radius: float, fill: str, opacity: float = 1.0) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{fill}" opacity="{opacity}"/>'


def page_start(title: str, kicker: str, number: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{LIGHT}"/>',
        rect(0, 0, WIDTH, 126, NAVY, radius=0),
        text(70, 42, kicker.upper(), 14, ORANGE, "700"),
        text(70, 93, title, 34, WHITE, "700"),
        text(WIDTH - 70, 46, "LAB 03", 15, "#b7d0e1", "700", anchor="end"),
        text(WIDTH - 70, 91, f"{number:02d}", 26, WHITE, "700", anchor="end"),
    ]


def page_end(parts: list[str], number: int) -> str:
    parts.extend([
        line(70, 1688, WIDTH - 70, 1688),
        text(70, 1722, "Evolutionary Computation - Local Search", 14, MUTED),
        text(WIDTH - 70, 1722, f"{AUTHOR_ONE} - {AUTHOR_TWO}   |   {number:02d}", 14, MUTED, anchor="end"),
        "</svg>",
    ])
    return "\n".join(parts)


def table(parts: list[str], x: int, y: int, widths: list[int], headers: list[str], rows: list[list[str]],
          row_height: int = 42, font_size: int = 16,
          highlight_cells: dict[tuple[int, int], str] | None = None,
          bold_cells: set[tuple[int, int]] | None = None) -> int:
    total = sum(widths)
    highlight_cells = highlight_cells or {}
    bold_cells = bold_cells or set()
    parts.append(rect(x, y, total, row_height, NAVY, radius=8))
    cursor = x
    for width, header in zip(widths, headers):
        parts.append(text(cursor + width / 2, y + row_height / 2 + font_size * 0.35,
                          header, font_size, WHITE, "700", anchor="middle"))
        cursor += width
    for row_index, row in enumerate(rows):
        row_y = y + row_height * (row_index + 1)
        parts.append(rect(x, row_y, total, row_height, WHITE if row_index % 2 == 0 else "#eef3f7", radius=0))
        cursor = x
        for column_index, (width, value) in enumerate(zip(widths, row)):
            cell = (row_index, column_index)
            if cell in highlight_cells:
                parts.append(rect(cursor + 3, row_y + 3, width - 6, row_height - 6,
                                  highlight_cells[cell], radius=6))
            weight = "700" if cell in bold_cells else "400"
            cell_font_size = font_size + 2 if cell in bold_cells else font_size
            parts.append(text(cursor + width / 2, row_y + row_height / 2 + cell_font_size * 0.35,
                              value, cell_font_size, INK, weight, anchor="middle"))
            cursor += width
    parts.append(rect(x, y, total, row_height * (len(rows) + 1), "none", GRID, 8))
    return row_height * (len(rows) + 1)


def read_stats_file(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_stats() -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for instance in ("TSPA", "TSPB"):
        rows: list[dict[str, str]] = []
        for method_id, _, _, source in ALL_METHODS:
            directory = {"lab01": LAB01_EVALUATION, "lab02": LAB02_EVALUATION, "lab03": EVALUATION}[source]
            row = next(row for row in read_stats_file(directory / f"{instance}_stats.csv")
                       if row["method_name"] == method_id)
            rows.append(row)
        result[instance] = rows
    return result


def read_times() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for instance in ("TSPA", "TSPB"):
        times: dict[str, str] = {}
        for method_id, _, _, source in ALL_METHODS:
            directory = {"lab01": LAB01_EVALUATION, "lab02": LAB02_EVALUATION, "lab03": EVALUATION}[source]
            row = next(row for row in read_stats_file(directory / f"{instance}_times.csv")
                       if row["method_name"] == method_id)
            times[method_id] = row["time"]
        result[instance] = times
    return result


def local_artifact(instance: str, stem: str, worst: bool = False) -> Path:
    suffix = "_worst" if worst else ""
    return EVALUATION / "results" / f"{instance}_{stem}{suffix}.csv"


def read_route(instance: str, stem: str, worst: bool = False) -> list[int]:
    return [int(line) for line in local_artifact(instance, stem, worst).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def plot_path(instance: str, stem: str, worst: bool = False) -> Path:
    suffix = "_worst" if worst else ""
    return EVALUATION / "plots" / f"{instance}_{stem}{suffix}.svg"


def route_lines(route: list[int], max_chars: int = 42) -> list[str]:
    lines: list[str] = []
    current = ""
    for node in route:
        token = str(node)
        candidate = token if not current else f"{current} {token}"
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines or [""]


def render_plot(path: Path) -> Path:
    BUILD.mkdir(exist_ok=True)
    output = BUILD / path.stem.replace(" ", "_")
    output = output.with_suffix(".png")
    if not output.exists() or output.stat().st_mtime < path.stat().st_mtime:
        magick = shutil.which("magick") or r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
        subprocess.run([magick, str(path), "-resize", "800x800", str(output)], check=True)
    return output


def image(parts: list[str], path: Path, x: int, y: int, width: int, height: int) -> None:
    encoded = base64.b64encode(render_plot(path).read_bytes()).decode("ascii")
    parts.append(f'<image x="{x}" y="{y}" width="{width}" height="{height}" preserveAspectRatio="xMidYMid meet" '
                 f'xlink:href="data:image/png;base64,{encoded}"/>')


def cover_page(number: int) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{LIGHT}"/>',
        rect(0, 0, WIDTH, 650, NAVY, radius=0),
        circle(1080, 65, 210, BLUE, 0.36),
        circle(1120, 150, 125, TEAL, 0.42),
        circle(88, 625, 230, ORANGE, 0.92),
        text(76, 86, "EVOLUTIONARY COMPUTATION", 17, "#b7d0e1", "700"),
        text(76, 160, "LABORATORY 03", 22, ORANGE, "700"),
        text(76, 250, "Local", 66, WHITE, "700"),
        text(76, 326, "search", 66, WHITE, "700"),
        text(80, 402, "for the Traveling Salesperson Problem with Node Costs", 20, "#d9e8f1"),
        rect(76, 470, 400, 70, "#ffffff", radius=35, opacity=0.12),
        text(112, 515, "ASSIGNMENT 3 - REPORT", 18, WHITE, "700"),
        rect(76, 570, 1088, 112, "#1b4669", "#477c9d", 18),
        text(112, 607, "SOURCE REPOSITORY", 14, ORANGE, "700"),
        text(112, 651, REPOSITORY_URL, 16, WHITE, "700"),
        text(76, 716, "Authors", 18, BLUE, "700"),
        text(76, 760, AUTHOR_ONE, 34, INK, "700"),
        text(76, 800, "160301", 20, MUTED),
        text(390, 760, AUTHOR_TWO, 34, INK, "700"),
        text(390, 800, "160292", 20, MUTED),
        rect(76, 890, 1088, 260, WHITE, GRID, 22),
        text(112, 950, "OBJECTIVE", 15, TEAL, "700"),
        text(112, 1012, "Minimize cycle length + selected node costs", 32, INK, "700"),
        text(112, 1068, "Improve feasible cycles through local search neighborhoods.", 20, MUTED),
        text(112, 1102, "The supplied instances contain 200 nodes, so every solution selects 100.", 20, MUTED),
        rect(76, 1220, 520, 190, PALE_BLUE, radius=20),
        text(110, 1270, "INSTANCES", 14, BLUE, "700"),
        text(110, 1324, "TSPA and TSPB", 31, INK, "700"),
        text(110, 1370, "200 nodes each - 100 selected", 18, MUTED),
        rect(644, 1220, 520, 190, PALE_TEAL, radius=20),
        text(678, 1270, "METHODS", 14, TEAL, "700"),
        text(678, 1324, "8 local-search variants", 28, INK, "700"),
        text(678, 1370, "200 evaluated solutions per method", 18, MUTED),
        line(76, 1510, 1164, 1510, GRID, 1),
        text(76, 1565, "Poznań University of Technology - Artificial Intelligence", 17, MUTED),
        text(1164, 1565, "November 2026", 17, MUTED, anchor="end"),
    ]
    return page_end(parts, number)


def problem_page(number: int) -> str:
    parts = page_start("1. Problem description", "01 - problem", number)
    parts.extend([
        text(70, 190, "The input consists of n nodes, each with integer planar coordinates (x, y) and an integer node cost.", 19, MUTED),
        text(70, 230, "The task is to choose exactly k = ceil(n / 2) distinct nodes and specify their cyclic visiting order.", 19, MUTED),
        text(70, 270, "The cycle must return from its last selected node to its first selected node.", 19, MUTED),
        rect(70, 330, 1100, 154, NAVY, radius=18),
        text(105, 374, "OBJECTIVE", 14, ORANGE, "700"),
        text(105, 428, "f(S) = cycle length(S) + sum of costs of selected nodes", 27, WHITE, "700"),
        rect(70, 540, 525, 260, PALE_BLUE, radius=20),
        rect(645, 540, 525, 260, PALE_TEAL, radius=20),
        text(105, 586, "DISTANCE", 15, BLUE, "700"),
        text(680, 586, "DATA SEPARATION", 15, TEAL, "700"),
        multiline(105, 638, [
            "d(i,j) = round(sqrt((xi-xj)^2 + (yi-yj)^2))",
            "",
            "Distances are calculated once",
            "and stored in a distance matrix.",
        ], 18, INK, line_height=35),
        multiline(680, 638, [
            "Optimization methods access",
            "the distance matrix and node",
            "costs, not the original coordinates.",
        ], 18, INK, line_height=35),
        text(70, 890, "For the supplied TSPA and TSPB instances, n = 200 and k = 100.", 20, INK, "700"),
        multiline(70, 946, wrap(
            "Local search starts from a feasible cycle and repeatedly tests a defined neighborhood. "
            "Every accepted move changes the selected-node set, the route order, or both while preserving feasibility.", 97), 19, MUTED, line_height=29),
        text(70, 1140, "Solution representation", 25, INK, "700"),
        rect(70, 1188, 1100, 230, WHITE, GRID, 20),
        multiline(108, 1240, [
            "A solution is an ordered list of k distinct node indices.",
            "The closing edge from the last node to the first is included in the objective.",
            "All reported indices are zero-based, matching the supplied solution checker.",
        ], 19, MUTED, line_height=36),
    ])
    return page_end(parts, number)


def code_card(parts: list[str], x: int, y: int, width: int, height: int, title: str,
              description: str, code: list[str], accent: str) -> None:
    parts.append(rect(x, y, width, height, WHITE, GRID, 20))
    parts.append(rect(x, y, 9, height, accent, radius=5))
    parts.append(text(x + 32, y + 43, title, 24, INK, "700"))
    parts.append(multiline(x + 32, y + 78, wrap(description, 45), 16, MUTED, line_height=23))
    code_y = y + 148
    code_height = height - 172
    parts.append(rect(x + 24, code_y, width - 48, code_height, NAVY, radius=12))
    parts.append(multiline(x + 44, code_y + 34, code, 14, "#e2eef5", family="Consolas", line_height=21))


def algorithms_page(number: int) -> str:
    parts = page_start("2. Algorithms and pseudocode", "02 - algorithms", number)
    parts.extend([
        text(70, 158, "Each variant accepts either a random feasible cycle or the best greedy construction as its starting solution S0.", 17, MUTED),
        text(70, 190, "D stores rounded distances, C stores node costs, and every variant also allows selected-to-unselected replacement moves.", 17, MUTED),
    ])
    code_card(parts, 70, 220, 530, 620, "2.1 Greedy search / node exchange",
              "Standalone procedure for greedy improvement with intra-route swaps and selected-to-unselected replacements.", [
                  "Input: D[i][j], C[i], k = ceil(n / 2)",
                  "Input: feasible start cycle S0",
                  "  S0 is random or best greedy; S <- S0",
                  "F(S) = sum D[S[p]][S[next(p)]] + sum C[S[p]]",
                  "swap_delta = changed edge sum after swapping i,j",
                  "replace_delta(p,v) = new two edges - old two edges",
                  "  + C[v] - C[S[p]]; v is currently unused",
                  "repeat:",
                  "  M <- all swaps (i,j) and replacements (p,v)",
                  "  shuffle M; improved <- false",
                  "  for m in M:",
                  "    delta <- swap_delta or replace_delta",
                  "    if delta < 0: apply m; F <- F + delta",
                  "      improved <- true; break",
                  "  if not improved: stop",
                  "return S, F(S)",
              ], TEAL)
    code_card(parts, 640, 220, 530, 620, "2.2 Greedy search / 2-opt",
              "Standalone procedure for greedy improvement with 2-opt route reversals and replacements.", [
                  "Input: D[i][j], C[i], k = ceil(n / 2)",
                  "Input: feasible start cycle S0",
                  "  S0 is random or best greedy; S <- S0",
                  "F(S) = sum D[S[p]][S[next(p)]] + sum C[S[p]]",
                  "two_opt_delta(i,j) = D[a][S[j]] + D[S[i]][b]",
                  "  - D[a][S[i]] - D[S[j]][b]",
                  "  where a = previous(i), b = next(j)",
                  "replace_delta(p,v) = new two edges - old two edges",
                  "  + C[v] - C[S[p]]; v is currently unused",
                  "repeat: shuffle all 2-opt and replacement moves",
                  "  for m in shuffled moves:",
                  "    delta <- two_opt_delta or replace_delta",
                  "    if delta < 0: apply m; F <- F + delta; break",
                  "  if no move was applied: stop",
                  "return S, F(S)",
              ], TEAL)
    code_card(parts, 70, 865, 530, 620, "2.3 Steepest search / node exchange",
              "Standalone procedure for choosing the best improving swap or selected-to-unselected replacement.", [
                  "Input: D[i][j], C[i], k = ceil(n / 2)",
                  "Input: feasible start cycle S0",
                  "  S0 is random or best greedy; S <- S0",
                  "F(S) = sum D[S[p]][S[next(p)]] + sum C[S[p]]",
                  "swap_delta = changed edge sum after swapping i,j",
                  "replace_delta(p,v) = new two edges - old two edges",
                  "  + C[v] - C[S[p]]; v is currently unused",
                  "repeat: best_delta <- 0; best_move <- none",
                  "  for every swap (i,j) and replacement (p,v):",
                  "    delta <- swap_delta or replace_delta",
                  "    if delta < best_delta: save move and delta",
                  "  if best_move is none: stop",
                  "  apply best_move; F <- F + best_delta",
                  "return S, F(S)",
              ], BLUE)
    code_card(parts, 640, 865, 530, 620, "2.4 Steepest search / 2-opt",
              "Standalone procedure for choosing the best improving 2-opt reversal or replacement.", [
                  "Input: D[i][j], C[i], k = ceil(n / 2)",
                  "Input: feasible start cycle S0",
                  "  S0 is random or best greedy; S <- S0",
                  "F(S) = sum D[S[p]][S[next(p)]] + sum C[S[p]]",
                  "two_opt_delta(i,j) = D[a][S[j]] + D[S[i]][b]",
                  "  - D[a][S[i]] - D[S[j]][b]",
                  "  where a = previous(i), b = next(j)",
                  "replace_delta(p,v) = new two edges - old two edges",
                  "  + C[v] - C[S[p]]; v is currently unused",
                  "repeat: best_delta <- 0; best_move <- none",
                  "  for every 2-opt and replacement move:",
                  "    delta <- two_opt_delta or replace_delta",
                  "    if delta < best_delta: save move and delta",
                  "  if best_move is none: stop",
                  "  apply best_move; F <- F + best_delta",
                  "return S, F(S)",
              ], BLUE)
    return page_end(parts, number)


def comparison_page(number: int, stats: dict[str, list[dict[str, str]]]) -> str:
    parts = page_start("3. Algorithm comparison", "03 - comparison", number)
    parts.extend([
        text(70, 190, "Local-search names follow: start type / improvement rule / intra-route move.", 17, MUTED),
        text(70, 224, "Random start = a shuffled feasible cycle; Best greedy start = the best Lab 01/02 constructive start.", 17, MUTED),
        text(70, 258, "Steepest = best improving move; Greedy = first improving move. Every variant also uses selected-to-unselected exchange.", 17, MUTED),
        text(70, 296, "Randomization: before every greedy-search iteration, one combined neighborhood is built with all allowed intra-route", 16, MUTED),
        text(70, 324, "moves (node exchange or 2-opt) and all selected-to-unselected replacements. The complete list is shuffled with", 16, MUTED),
        text(70, 352, "std::shuffle using the method-specific seeded generator, so no move type is always examined first. Greedy search", 16, MUTED),
        text(70, 380, "then accepts the first negative-delta move; after applying it, a new combined neighborhood is built and shuffled.", 16, MUTED),
        text(70, 408, "Steepest variants use the same combined neighborhood but do not shuffle it; they evaluate every move and choose the most negative delta.", 16, MUTED),
    ])
    labels = {method_id: label for method_id, label, _, _ in ALL_METHODS}
    rows = []
    for tspa_row, tspb_row in zip(stats["TSPA"], stats["TSPB"]):
        rows.append([
            labels[tspa_row["method_name"]],
            f"{fmt_average(tspa_row['avg'])}({fmt(tspa_row['min'])} - {fmt(tspa_row['max'])})",
            f"{fmt_average(tspb_row['avg'])}({fmt(tspb_row['min'])} - {fmt(tspb_row['max'])})",
        ])
    tspa_best_index = min(range(len(stats["TSPA"])), key=lambda index: float(stats["TSPA"][index]["avg"]))
    tspb_best_index = min(range(len(stats["TSPB"])), key=lambda index: float(stats["TSPB"][index]["avg"]))
    table(parts, 70, 458, [520, 290, 290],
          ["Algorithm", "TSPA: average (min - max)", "TSPB: average (min - max)"], rows,
          row_height=48, font_size=14,
          highlight_cells={(tspa_best_index, 1): "#ffd166", (tspb_best_index, 2): "#ffd166"},
          bold_cells={(tspa_best_index, 1), (tspb_best_index, 2)})
    tspa_best = stats["TSPA"][tspa_best_index]
    tspb_best = stats["TSPB"][tspb_best_index]
    parts.extend([
        rect(70, 1308, 18, 18, "#ffd166", radius=4),
        text(98, 1323, "lowest average", 14, MUTED),
        rect(70, 1368, 1100, 250, PALE_TEAL, radius=20),
        text(108, 1418, "Best averages in this comparison", 23, INK, "700"),
        multiline(108, 1468, wrap(
            f"TSPA: {labels[tspa_best['method_name']]} - {fmt_average(tspa_best['avg'])} "
            f"(minimum {fmt(tspa_best['min'])}, maximum {fmt(tspa_best['max'])}).", 92),
            18, MUTED, line_height=28),
        multiline(108, 1538, wrap(
            f"TSPB: {labels[tspb_best['method_name']]} - {fmt_average(tspb_best['avg'])} "
            f"(minimum {fmt(tspb_best['min'])}, maximum {fmt(tspb_best['max'])}).", 92),
            18, MUTED, line_height=28),
    ])
    return page_end(parts, number)


def legacy_table_page(number: int, instance: str, stats: dict[str, list[dict[str, str]]]) -> str:
    parts = page_start(f"4. Detailed evaluation - {instance}", "04 - legacy evaluation", number)
    parts.extend([
        text(70, 190, "This page preserves the detailed statistics table used in the previous reports.", 19, MUTED),
        text(70, 230, "The eight Lab 03 methods use 200 random or greedy starts, depending on the variant.", 19, MUTED),
        text(70, 270, "Minimum, maximum, average, and standard deviation are reported for each method.", 19, MUTED),
    ])
    labels = {method_id: label for method_id, label, _, _ in ALL_METHODS}
    rows = [[labels[row["method_name"]], fmt(row["min"]), fmt(row["max"]), fmt(row["avg"]), fmt(row["sd"])]
            for row in stats[instance]]
    minimum_index = min(range(len(stats[instance])), key=lambda index: float(stats[instance][index]["min"]))
    average_index = min(range(len(stats[instance])), key=lambda index: float(stats[instance][index]["avg"]))
    table(parts, 70, 320, [470, 140, 140, 190, 160],
          ["Algorithm", "Minimum", "Maximum", "Average", "Std. dev."], rows,
          row_height=44, font_size=14,
          highlight_cells={(minimum_index, 1): "#f4a261", (average_index, 3): "#ffd166"},
          bold_cells={(minimum_index, 1), (average_index, 3)})
    parts.extend([
        rect(70, 1085, 22, 22, "#f4a261", radius=4),
        text(106, 1103, "lowest minimum", 14, MUTED),
        rect(530, 1085, 22, 22, "#ffd166", radius=4),
        text(566, 1103, "lowest average", 14, MUTED),
    ])
    return page_end(parts, number)


def legacy_summary_page(number: int, instance: str, stats: dict[str, list[dict[str, str]]],
                        times: dict[str, dict[str, str]]) -> str:
    parts = page_start(f"4. Result summary - {instance}", "04 - summary and runtime", number)
    labels = {method_id: label for method_id, label, _, _ in ALL_METHODS}
    minimum_index = min(range(len(stats[instance])), key=lambda index: float(stats[instance][index]["min"]))
    average_index = min(range(len(stats[instance])), key=lambda index: float(stats[instance][index]["avg"]))
    best_min = stats[instance][minimum_index]
    best_avg = stats[instance][average_index]
    parts.extend([
        text(70, 240, "Result summary", 27, INK, "700"),
        rect(70, 290, 1100, 330, WHITE, GRID, 20),
        text(108, 365, "Best individual result", 20, BLUE, "700"),
        multiline(108, 415, wrap(
            f"{labels[best_min['method_name']]} with objective {fmt(best_min['min'])}.", 78),
            23, INK, line_height=34),
        text(108, 500, "Best average result", 20, TEAL, "700"),
        multiline(108, 550, wrap(
            f"{labels[best_avg['method_name']]} with average objective {fmt_average(best_avg['avg'])}.", 78),
            23, INK, line_height=34),
        text(70, 735, "Runtime reference", 27, INK, "700"),
    ])
    runtime_rows = [[labels[method_id], f"{times[instance][method_id]} ms"] for method_id, _, _, _ in ALL_METHODS]
    table(parts, 70, 785, [760, 340], ["Method", "Runtime"], runtime_rows, row_height=50, font_size=15)
    return page_end(parts, number)


def visual_page(number: int, instance: str, subset: list[tuple[str, str, str, str]],
                stats: dict[str, list[dict[str, str]]], worst: bool = False) -> str:
    mode = "Worst" if worst else "Best"
    section = "7 - worst solutions" if worst else "5 - best solutions"
    parts = page_start(f"{section.split(' - ')[0]}. {mode} solutions - {instance}", section, number)
    parts.append(text(70, 160, "The plots show node cost using colour and size. The line represents the closed cycle.", 17, MUTED))
    stat_by_id = {row["method_name"]: row for row in stats[instance]}
    for index, (method_id, label, stem, _) in enumerate(subset):
        y = 205 + index * 365
        row = stat_by_id[method_id]
        parts.append(rect(70, y, 1100, 335, WHITE, GRID, 18))
        parts.append(text(98, y + 38, label, 14 if len(label) > 30 else 19, INK, "700"))
        parts.append(text(98, y + 70, f"min={fmt(row['min'])}  max={fmt(row['max'])}  avg={fmt(row['avg'])}", 14, MUTED))
        objective = row["max"] if worst else row["min"]
        parts.append(rect(98, y + 92, 178, 38, PALE_ORANGE if worst else PALE_TEAL, radius=19))
        parts.append(text(187, y + 118, f"{mode.lower()} = {fmt(objective)}", 14, INK, "700", anchor="middle"))
        image(parts, plot_path(instance, stem, worst), 350, y + 10, 310, 310)
        parts.append(text(710, y + 58, f"{mode} solution nodes:", 15, BLUE, "700"))
        parts.append(multiline(710, y + 92, route_lines(read_route(instance, stem, worst)), 12, MUTED,
                               family="Consolas", line_height=17))
    return page_end(parts, number)


def dark_divider_page(number: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}"><rect width="{WIDTH}" height="{HEIGHT}" fill="{NAVY}"/></svg>')


def large_visual_page(number: int, instance: str, subset: list[tuple[str, str, str, str]],
                      stats: dict[str, list[dict[str, str]]], worst: bool = False) -> str:
    mode = "Worst" if worst else "Best"
    accent = ORANGE if worst else TEAL
    background = "#ffe8d8" if worst else "#def2ec"
    border = "#e4a06f" if worst else "#8ac5b6"
    parts = page_start(f"8. Large {mode.lower()} visualizations - {instance}",
                       f"appendix - {mode.lower()} solutions", number)
    stat_by_id = {row["method_name"]: row for row in stats[instance]}
    for y, (method_id, label, stem, _) in zip([155, 915], subset):
        row = stat_by_id[method_id]
        route = read_route(instance, stem, worst)
        objective = row["max"] if worst else row["min"]
        parts.append(rect(70, y, 1100, 740, background, border, 22))
        parts.append(rect(810, y + 24, 224, 40, accent, radius=20))
        parts.append(text(922, y + 50, f"{mode.upper()} SOLUTION", 14, WHITE, "700", anchor="middle"))
        parts.append(text(810, y + 98, label, 17 if len(label) > 29 else 20, INK, "700"))
        parts.append(multiline(810, y + 126, [f"min={fmt(row['min'])}", f"max={fmt(row['max'])}", f"avg={fmt(row['avg'])}"],
                               12, MUTED, line_height=18))
        parts.append(rect(810, y + 188, 210, 40, WHITE, border, 12))
        parts.append(text(915, y + 215, f"objective {fmt(objective)}", 14, INK, "700", anchor="middle"))
        image(parts, plot_path(instance, stem, worst), 85, y + 25, 700, 700)
        parts.append(text(810, y + 270, f"{mode} solution nodes:", 16, accent, "700"))
        parts.append(multiline(810, y + 306, route_lines(route, 25), 12, INK, family="Consolas", line_height=18))
        parts.append(text(810, y + 690, f"{len(set(route[:-1]))} selected nodes; closed route", 14, accent, "700"))
    return page_end(parts, number)


def conclusions_page(number: int, stats: dict[str, list[dict[str, str]]]) -> str:
    labels = {method_id: label for method_id, label, _, _ in ALL_METHODS}
    local_ids = {method_id for method_id, _, _, _ in LOCAL_METHODS}
    local_rows = {instance: [row for row in stats[instance] if row["method_name"] in local_ids]
                  for instance in ("TSPA", "TSPB")}
    tspa_best = min(local_rows["TSPA"], key=lambda row: float(row["avg"]))
    tspb_best = min(local_rows["TSPB"], key=lambda row: float(row["avg"]))
    parts = page_start("6. Conclusions", "06 - conclusions", number)
    parts.extend([
        multiline(70, 190, wrap("Local search improves the constructive starting solutions by repeatedly accepting objective-decreasing neighborhood moves.", 92), 20, MUTED, line_height=29),
        multiline(70, 248, wrap("The observed result depends on the starting-solution source, search policy, and intra-route neighborhood.", 92), 20, MUTED, line_height=29),
        rect(70, 310, 1100, 900, WHITE, GRID, 20),
        text(108, 370, "Main conclusions", 25, INK, "700"),
        multiline(108, 430, wrap(f"The best local-search average for TSPA was obtained by {labels[tspa_best['method_name']]} ({fmt(tspa_best['avg'])}), while TSPB was best with {labels[tspb_best['method_name']]} ({fmt(tspb_best['avg'])}).", 92), 19, MUTED, line_height=29),
        multiline(108, 544, wrap("Steepest search evaluates the whole neighborhood before moving, whereas greedy search accepts the first improving move in a randomized order. This creates a direct trade-off between search intensity and runtime.", 92), 19, MUTED, line_height=29),
        multiline(108, 704, wrap("The 2-opt neighborhood changes route order while preserving the selected set. Node exchange adds a different intra-route ordering neighborhood, and inter-route exchange can replace a selected node with an unused node and therefore changes the selected subset.", 92), 19, MUTED, line_height=29),
        multiline(108, 858, wrap("Greedy starts based on the best previous constructive methods are consistently stronger than random starts. Local search nevertheless improves both start types, showing that the neighborhood design contributes beyond construction quality.", 92), 19, MUTED, line_height=29),
        multiline(108, 1012, wrap("All generated routes passed structural validation and the delta-accounting assertion. The complete comparison table makes the improvement over Labs 01 and 02 directly visible.", 92), 19, MUTED, line_height=29),
        rect(70, 1305, 1100, 130, PALE_BLUE, "#b9d6e8", 20),
        text(108, 1350, "SOURCE REPOSITORY", 15, BLUE, "700"),
        text(108, 1400, REPOSITORY_URL, 18, INK, "700"),
        text(70, 1480, "The large-format best and worst local-search visualizations are presented in the appendix.", 17, INK, "700"),
    ])
    return page_end(parts, number)


def main() -> None:
    stats = read_stats()
    times = read_times()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir()
    pages = [
        cover_page(1),
        problem_page(2),
        algorithms_page(3),
        comparison_page(4, stats),
        legacy_table_page(5, "TSPA", stats),
        legacy_summary_page(6, "TSPA", stats, times),
        legacy_table_page(7, "TSPB", stats),
        legacy_summary_page(8, "TSPB", stats, times),
        visual_page(9, "TSPA", LOCAL_METHODS[:4], stats),
        visual_page(10, "TSPA", LOCAL_METHODS[4:], stats),
        visual_page(11, "TSPB", LOCAL_METHODS[:4], stats),
        visual_page(12, "TSPB", LOCAL_METHODS[4:], stats),
        conclusions_page(13, stats),
        visual_page(14, "TSPA", LOCAL_METHODS[:4], stats, True),
        visual_page(15, "TSPA", LOCAL_METHODS[4:], stats, True),
        visual_page(16, "TSPB", LOCAL_METHODS[:4], stats, True),
        visual_page(17, "TSPB", LOCAL_METHODS[4:], stats, True),
        dark_divider_page(18),
        large_visual_page(19, "TSPA", LOCAL_METHODS[0:2], stats),
        large_visual_page(20, "TSPA", LOCAL_METHODS[2:4], stats),
        large_visual_page(21, "TSPA", LOCAL_METHODS[4:6], stats),
        large_visual_page(22, "TSPA", LOCAL_METHODS[6:8], stats),
        large_visual_page(23, "TSPB", LOCAL_METHODS[0:2], stats),
        large_visual_page(24, "TSPB", LOCAL_METHODS[2:4], stats),
        large_visual_page(25, "TSPB", LOCAL_METHODS[4:6], stats),
        large_visual_page(26, "TSPB", LOCAL_METHODS[6:8], stats),
        large_visual_page(27, "TSPA", LOCAL_METHODS[0:2], stats, True),
        large_visual_page(28, "TSPA", LOCAL_METHODS[2:4], stats, True),
        large_visual_page(29, "TSPA", LOCAL_METHODS[4:6], stats, True),
        large_visual_page(30, "TSPA", LOCAL_METHODS[6:8], stats, True),
        large_visual_page(31, "TSPB", LOCAL_METHODS[0:2], stats, True),
        large_visual_page(32, "TSPB", LOCAL_METHODS[2:4], stats, True),
        large_visual_page(33, "TSPB", LOCAL_METHODS[4:6], stats, True),
        large_visual_page(34, "TSPB", LOCAL_METHODS[6:8], stats, True),
    ]
    page_paths = []
    for index, page in enumerate(pages, start=1):
        path = BUILD / f"page_{index:02d}.svg"
        path.write_text(page, encoding="utf-8")
        page_paths.append(str(path))
    magick = shutil.which("magick") or r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
    subprocess.run([magick, "-density", "150", *page_paths, "-background", WHITE, "-alpha", "remove",
                    "-compress", "JPEG", "-quality", "88", str(REPORT)], check=True)
    print(f"Generated {REPORT} ({len(pages)} pages)")


if __name__ == "__main__":
    main()
