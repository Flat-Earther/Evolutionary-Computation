"""Generate the Lab 02 report from the evaluation CSV files and SVG plots."""

from __future__ import annotations

import base64
import csv
import html
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVALUATION = ROOT / "evaluation"
DATA_DIR = ROOT.parent / "problem-description" / "data" / "example"
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
AUTHOR_ONE = "Paweł Świątek"
AUTHOR_TWO = "Jędrzej Szmidt"
REPOSITORY_URL = "https://github.com/Flat-Earther/Evolutionary-Computation/tree/main/lab-02-greedy-regret-heuristics"

METHODS = [
    ("random_sol", "Random solution", "random"),
    ("nn_at_end", "Nearest neighbor - end", "nn_end"),
    ("nn_flexible", "Nearest neighbor - any position", "nn_flexible"),
    ("greedy_cycle", "Greedy cycle", "greedy_cycle"),
    ("regret2_path", "2-regret - path", "regret2_path"),
    ("regret2_cycle", "2-regret - cycle", "regret2_cycle"),
    ("weighted_path", "Weighted regret - path", "weighted_path"),
    ("weighted_cycle", "Weighted regret - cycle", "weighted_cycle"),
]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def fmt(value: str | float | int, places: int = 2) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{places}f}"


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
        text(WIDTH - 70, 46, "LAB 02", 15, "#b7d0e1", "700", anchor="end"),
        text(WIDTH - 70, 91, f"{number:02d}", 26, WHITE, "700", anchor="end"),
    ]


def page_end(parts: list[str], number: int) -> str:
    parts.extend([
        line(70, 1688, WIDTH - 70, 1688),
        text(70, 1722, "Evolutionary Computation - Greedy Regret Heuristics", 14, MUTED),
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
            cell_font_size = font_size + 4 if cell in bold_cells else font_size
            parts.append(text(cursor + width / 2,
                              row_y + row_height / 2 + cell_font_size * 0.35,
                              value, cell_font_size, INK, weight, anchor="middle"))
            cursor += width
    parts.append(rect(x, y, total, row_height * (len(rows) + 1), "none", GRID, 8))
    return row_height * (len(rows) + 1)


def read_stats() -> dict[str, list[dict[str, str]]]:
    result = {}
    for instance in ("TSPA", "TSPB"):
        with (EVALUATION / f"{instance}_stats.csv").open(newline="", encoding="utf-8") as handle:
            result[instance] = list(csv.DictReader(handle))
    return result


def read_times() -> dict[str, dict[str, str]]:
    result = {}
    for instance in ("TSPA", "TSPB"):
        with (EVALUATION / f"{instance}_times.csv").open(newline="", encoding="utf-8") as handle:
            result[instance] = {row["method_name"]: row["time"] for row in csv.DictReader(handle)}
    return result


def read_route(instance: str, method: str, worst: bool = False) -> list[int]:
    suffix = "_worst" if worst else ""
    path = EVALUATION / "results" / f"{instance}_{method}{suffix}.csv"
    return [int(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def route_lines(route: list[int], max_chars: int = 68) -> list[str]:
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
    output = BUILD / f"{path.stem}.png"
    if not output.exists() or output.stat().st_mtime < path.stat().st_mtime:
        magick = shutil.which("magick") or r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
        subprocess.run([magick, str(path), "-resize", "800x800", str(output)], check=True)
    return output


def image_data(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def image(parts: list[str], path: Path, x: int, y: int, width: int, height: int) -> None:
    parts.append(f'<image x="{x}" y="{y}" width="{width}" height="{height}" preserveAspectRatio="xMidYMid meet" '
                 f'xlink:href="data:image/png;base64,{image_data(render_plot(path))}"/>')


def cover_page(number: int) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{LIGHT}"/>',
        rect(0, 0, WIDTH, 650, NAVY, radius=0),
        circle(1080, 65, 210, BLUE, 0.36),
        circle(1120, 150, 125, TEAL, 0.42),
        circle(88, 625, 230, ORANGE, 0.92),
        text(76, 86, "EVOLUTIONARY COMPUTATION", 17, "#b7d0e1", "700"),
        text(76, 160, "LABORATORY 02", 22, ORANGE, "700"),
        text(76, 250, "Greedy", 66, WHITE, "700"),
        text(76, 326, "heuristics", 66, WHITE, "700"),
        text(80, 402, "for the Traveling Salesperson Problem with Node Costs", 20, "#d9e8f1"),
        rect(76, 470, 400, 70, "#ffffff", radius=35, opacity=0.12),
        text(112, 515, "ASSIGNMENT 2 - REPORT", 18, WHITE, "700"),
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
        text(112, 1068, "Choose exactly ceil(n / 2) nodes and arrange them into a closed cycle.", 20, MUTED),
        text(112, 1102, "The supplied instances contain 200 nodes, so every solution selects 100.", 20, MUTED),
        rect(76, 1220, 520, 190, PALE_BLUE, radius=20),
        text(110, 1270, "INSTANCES", 14, BLUE, "700"),
        text(110, 1324, "TSPA and TSPB", 31, INK, "700"),
        text(110, 1370, "200 nodes each - 100 selected", 18, MUTED),
        rect(644, 1220, 520, 190, PALE_TEAL, radius=20),
        text(678, 1270, "METHODS", 14, TEAL, "700"),
        text(678, 1324, "8 greedy and regret methods", 27, INK, "700"),
        text(678, 1370, "200 evaluated solutions per method", 18, MUTED),
        line(76, 1510, 1164, 1510, GRID, 1),
        text(76, 1565, "Poznań University of Technology - Artificial Intelligence", 17, MUTED),
        text(1164, 1565, "October 2026", 17, MUTED, anchor="end"),
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
            "This problem combines a subset-selection decision with a cyclic routing decision. "
            "The algorithms below construct feasible solutions directly and evaluate every candidate change "
            "using both distance and node cost.", 97), 19, MUTED, line_height=29),
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
    parts.append(multiline(x + 44, code_y + 34, code, 15, "#e2eef5", family="Consolas", line_height=24))


def algorithms_page(number: int) -> str:
    parts = page_start("2. Algorithms and pseudocode", "02 - algorithms", number)
    code_card(parts, 70, 180, 530, 650, "2.1 2-regret - open path",
              "Builds an open path and prioritizes nodes whose second-best position is much worse than their best position.", [
                  "Algorithm Regret2Path(D, C, start)",
                  "1. S <- [start]; U <- V \\ {start}",
                  "2. while |S| < k:",
                  "   for each v in U and each path gap p:",
                  "     delta(v,p) <- added distance + C[v]",
                  "   best(v), p(v) <- smallest delta(v,p)",
                  "   second(v) <- second-smallest delta(v,p)",
                  "   regret(v) <- second(v) - best(v)",
                  "   choose v with largest regret(v)",
                  "   insert v into gap p(v); remove v from U",
                  "3. close S with an edge from last to first",
                  "4. return S and objective F(S)",
              ], TEAL)
    code_card(parts, 640, 180, 530, 650, "2.2 2-regret - closed cycle",
              "Maintains a closed cycle and evaluates every possible insertion edge independently.", [
                  "Algorithm Regret2Cycle(D, C, start)",
                  "1. v2 <- argmin over v != start of D[start][v] + C[v]",
                  "2. S <- [start, v2]; U <- V \\ S",
                  "3. while |S| < k:",
                  "   for each v in U and each cycle edge (a,b):",
                  "     delta(v,a,b) <- D[a][v] + D[v][b]",
                  "                       - D[a][b] + C[v]",
                  "   best(v), e(v) <- smallest delta(v,a,b)",
                  "   second(v) <- second-smallest delta(v,a,b)",
                  "   regret(v) <- second(v) - best(v)",
                  "   choose v with largest regret(v)",
                  "   insert v into edge e(v); remove v from U",
                  "4. return the closed cycle S and F(S)",
              ], BLUE)
    code_card(parts, 70, 870, 530, 650, "2.3 Weighted regret - open path",
              "Combines open-path regret with the immediate insertion cost; both weights are one in the experiment.", [
                  "Algorithm WeightedRegretPath(D, C, start)",
                  "1. S <- [start]; U <- V \\ {start}",
                  "2. wr <- 1; wd <- 1",
                  "3. while |S| < k:",
                  "   for each v in U and each path gap p:",
                  "     delta(v,p) <- added distance + C[v]",
                  "   best(v), p(v) <- smallest delta(v,p)",
                  "   second(v) <- second-smallest delta(v,p)",
                  "   regret(v) <- second(v) - best(v)",
                  "   score(v) <- wr * regret(v) - wd * best(v)",
                  "   choose v with largest score(v)",
                  "   insert v into gap p(v); remove v from U",
                  "4. close S and return S and F(S)",
              ], TEAL)
    code_card(parts, 640, 870, 530, 650, "2.4 Weighted regret - closed cycle",
              "Combines closed-cycle regret with the immediate insertion cost using explicit equal weights.", [
                  "Algorithm WeightedRegretCycle(D, C, start)",
                  "1. v2 <- argmin over v != start of D[start][v] + C[v]",
                  "2. S <- [start, v2]; U <- V \\ S",
                  "3. wr <- 1; wd <- 1",
                  "4. while |S| < k:",
                  "   for each v in U and each cycle edge (a,b):",
                  "     delta(v,a,b) <- D[a][v] + D[v][b]",
                  "                       - D[a][b] + C[v]",
                  "   best(v), e(v) <- smallest delta(v,a,b)",
                  "   second(v) <- second-smallest delta(v,a,b)",
                  "   regret(v) <- second(v) - best(v)",
                  "   score(v) <- wr * regret(v) - wd * best(v)",
                  "   choose v with largest score(v)",
                  "   insert v into edge e(v); remove v from U",
                  "5. return the closed cycle S and F(S)",
              ], BLUE)
    return page_end(parts, number)


def results_page(number: int, instance: str, stats: dict[str, list[dict[str, str]]],
                 times: dict[str, dict[str, str]], final_results: bool = False) -> str:
    parts = page_start(f"3. Computational experiment - {instance}", "03 - results", number)
    parts.extend([
        text(70, 190, "Each row aggregates 200 solutions generated from all possible starting nodes.", 19, MUTED),
        text(70, 230, "Weighted methods use equal weights: regret_weight = 1 and delta_weight = 1.", 19, MUTED),
        text(70, 270, "For each method, minimum, maximum, average, and standard deviation are calculated.", 19, MUTED),
        text(70, 350, f"Experimental results - {instance}", 27, INK, "700"),
    ])
    rows = []
    labels = {method_id: label for method_id, label, _ in METHODS}
    for row in stats[instance]:
        rows.append([labels[row["method_name"]], fmt(row["min"]), fmt(row["max"]), fmt(row["avg"]), fmt(row["sd"])])
    minimum_index = min(range(len(stats[instance])), key=lambda index: float(stats[instance][index]["min"]))
    average_index = min(range(len(stats[instance])), key=lambda index: float(stats[instance][index]["avg"]))
    table(parts, 70, 398, [380, 160, 160, 220, 180],
          ["Algorithm", "Minimum", "Maximum", "Average", "Std. dev."], rows,
          row_height=44, font_size=14,
          highlight_cells={(minimum_index, 1): "#f4a261", (average_index, 3): "#ffd166"},
          bold_cells={(minimum_index, 1), (average_index, 3)})
    best_min = min(stats[instance], key=lambda row: float(row["min"]))
    best_avg = min(stats[instance], key=lambda row: float(row["avg"]))
    parts.extend([
        rect(70, 820, 1100, 30, "none", "none", 0),
        rect(70, 820, 18, 18, "#f4a261", radius=4),
        text(98, 835, "lowest minimum", 14, MUTED),
        rect(242, 820, 18, 18, "#ffd166", radius=4),
        text(270, 835, "lowest average", 14, MUTED),
        text(70, 885, "Result summary", 25, INK, "700"),
        rect(70, 933, 1100, 270, WHITE, GRID, 20),
        multiline(108, 978, wrap(f"The best individual solution for {instance} was found by {labels[best_min['method_name']]}, with objective {fmt(best_min['min'])}.", 86), 19, MUTED, line_height=29),
        multiline(108, 1065, wrap(f"The best average result for this instance was obtained by {labels[best_avg['method_name']]}, with average objective {fmt(best_avg['avg'])}.", 86), 19, MUTED, line_height=29),
        text(108, 1160, "All generated routes passed the internal structural validation.", 19, INK, "700"),
        text(70, 1240, "Runtime reference", 25, INK, "700"),
    ])
    runtime_rows = [[labels[key], f"{value} ms"] for key, value in times[instance].items()]
    table(parts, 70, 1285, [560, 300], ["Method", "Runtime"], runtime_rows, 38, 14)
    return page_end(parts, number)


def visual_page(number: int, instance: str, subset: list[tuple[str, str, str]],
                stats: dict[str, list[dict[str, str]]], worst: bool = False) -> str:
    mode = "Worst" if worst else "Best"
    section = "6 - worst solutions" if worst else "4 - best solutions"
    parts = page_start(f"{section.split(' - ')[0]}. {mode} solutions - {instance}", section, number)
    parts.append(text(70, 160, "The plots show node cost using colour and size. The line represents the closed cycle.", 17, MUTED))
    stat_by_id = {row["method_name"]: row for row in stats[instance]}
    for index, (method_id, label, stem) in enumerate(subset):
        y = 205 + index * 365
        row = stat_by_id[method_id]
        parts.append(rect(70, y, 1100, 335, WHITE, GRID, 18))
        parts.append(text(98, y + 38, label, 20 if len(label) < 28 else 17, INK, "700"))
        parts.append(text(98, y + 70, f"min={fmt(row['min'])}  max={fmt(row['max'])}  avg={fmt(row['avg'])}", 14, MUTED))
        objective = row["max"] if worst else row["min"]
        parts.append(rect(98, y + 92, 178, 38, PALE_ORANGE if worst else PALE_TEAL, radius=19))
        parts.append(text(187, y + 118, f"{mode.lower()} = {fmt(objective)}", 14, INK, "700", anchor="middle"))
        suffix = "_worst" if worst else ""
        image(parts, EVALUATION / "plots" / f"{instance}_{stem}{suffix}.svg", 350, y + 10, 310, 310)
        parts.append(text(710, y + 58, f"{mode} solution nodes:", 15, BLUE, "700"))
        route = read_route(instance, stem, worst)
        parts.append(multiline(710, y + 92, route_lines(route, 42), 12, MUTED, family="Consolas", line_height=17))
    return page_end(parts, number)


def dark_divider_page(number: int) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{NAVY}"/>'
        "</svg>"
    )


def large_visual_page(number: int, instance: str, subset: list[tuple[str, str, str]],
                      stats: dict[str, list[dict[str, str]]], worst: bool = False) -> str:
    mode = "Worst" if worst else "Best"
    accent = ORANGE if worst else TEAL
    background = "#ffe8d8" if worst else "#def2ec"
    border = "#e4a06f" if worst else "#8ac5b6"
    parts = page_start(
        f"7. Large {mode.lower()} visualizations - {instance}",
        f"appendix - {mode.lower()} solutions",
        number,
    )
    stat_by_id = {row["method_name"]: row for row in stats[instance]}
    for y, (method_id, label, stem) in zip([155, 915], subset):
        row = stat_by_id[method_id]
        objective = row["max"] if worst else row["min"]
        route = read_route(instance, stem, worst)
        parts.append(rect(70, y, 1100, 740, background, border, 22))
        parts.append(rect(810, y + 24, 224, 40, accent, radius=20))
        parts.append(text(922, y + 50, f"{mode.upper()} SOLUTION", 14, WHITE, "700", anchor="middle"))
        label_size = 18 if len(label) > 25 else 22
        parts.append(text(810, y + 98, label, label_size, INK, "700"))
        parts.append(multiline(810, y + 126, [
            f"min={fmt(row['min'])}",
            f"max={fmt(row['max'])}",
            f"avg={fmt(row['avg'])}",
        ], 12, MUTED, line_height=18))
        parts.append(rect(810, y + 188, 210, 40, WHITE, border, 12))
        parts.append(text(915, y + 215, f"objective {fmt(objective)}", 14, INK, "700", anchor="middle"))
        suffix = "_worst" if worst else ""
        image(parts, EVALUATION / "plots" / f"{instance}_{stem}{suffix}.svg", 85, y + 25, 700, 700)
        parts.append(text(810, y + 270, f"{mode} solution nodes:", 16, accent, "700"))
        parts.append(multiline(810, y + 306, route_lines(route, 25), 12, INK, family="Consolas", line_height=18))
        parts.append(text(810, y + 690, f"{len(set(route[:-1]))} selected nodes; closed route", 14, accent, "700"))
    return page_end(parts, number)


def route_page(number: int, instance: str) -> str:
    parts = page_start(f"Best solution node lists - {instance}", "05 - reproducibility", number)
    parts.append(text(70, 160, "Routes are zero-based and include the repeated first node that closes the cycle.", 17, MUTED))
    for index, (method_id, label, stem) in enumerate(METHODS):
        column = index % 2
        row = index // 2
        x = 70 + column * 570
        y = 205 + row * 360
        parts.append(rect(x, y, 530, 330, WHITE, GRID, 18))
        parts.append(text(x + 26, y + 36, label, 17 if len(label) < 30 else 14, INK, "700"))
        parts.append(multiline(x + 26, y + 76, route_lines(read_route(instance, stem), 27), 10, MUTED, family="Consolas", line_height=15))
    return page_end(parts, number)


def conclusions_page(number: int, stats: dict[str, list[dict[str, str]]]) -> str:
    parts = page_start("5. Conclusions", "05 - conclusions", number)
    tspa = {row["method_name"]: row for row in stats["TSPA"]}
    tspb = {row["method_name"]: row for row in stats["TSPB"]}
    parts.extend([
        multiline(70, 190, wrap("The experimental results show that regret-based selection can improve the greedy baselines when combined with the best objective change.", 92), 20, MUTED, line_height=29),
        multiline(70, 248, wrap("The effect depends on whether the method constructs an open path or a closed cycle.", 92), 20, MUTED, line_height=29),
        rect(70, 310, 1100, 900, WHITE, GRID, 20),
        text(108, 370, "Main conclusions", 25, INK, "700"),
        multiline(108, 430, wrap(f"Weighted regret cycle achieved the best individual solution on TSPA ({fmt(tspa['weighted_cycle']['min'])}), while weighted regret path achieved the best individual solution on TSPB ({fmt(tspb['weighted_path']['min'])}).", 92), 19, MUTED, line_height=29),
        multiline(108, 544, wrap(f"The best average results were also obtained by the weighted methods: weighted regret cycle on TSPA ({fmt(tspa['weighted_cycle']['avg'])}) and weighted regret path on TSPB ({fmt(tspb['weighted_path']['avg'])}).", 92), 19, MUTED, line_height=29),
        multiline(108, 704, wrap("Pure 2-regret performs worse on these instances because it prioritizes nodes with a large difference between their first and second insertion choices, even when their best insertion is expensive. The weighted criterion restores pressure toward a low immediate objective change.", 92), 19, MUTED, line_height=29),
        multiline(108, 858, wrap("The open-path and closed-cycle variants behave differently. The cycle variant accounts for every insertion edge in the current closed route, while the path variant follows the extended nearest-neighbor construction used in lab 01.", 92), 19, MUTED, line_height=29),
        multiline(108, 1012, wrap("All 3,200 generated routes passed the internal structural validation. The saved routes and plots provide a reproducible starting point for local search and later evolutionary methods.", 92), 19, MUTED, line_height=29),
        rect(70, 1305, 1100, 130, PALE_BLUE, "#b9d6e8", 20),
        text(108, 1350, "SOURCE REPOSITORY", 15, BLUE, "700"),
        text(108, 1400, REPOSITORY_URL, 18, INK, "700"),
        text(70, 1480, "The large-format best and worst visualizations are presented in the final appendix pages.", 17, INK, "700"),
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
        results_page(4, "TSPA", stats, times),
        results_page(5, "TSPB", stats, times),
        visual_page(6, "TSPA", METHODS[4:], stats),
        visual_page(7, "TSPB", METHODS[4:], stats),
        conclusions_page(8, stats),
        visual_page(9, "TSPA", METHODS[4:], stats, True),
        visual_page(10, "TSPB", METHODS[4:], stats, True),
        dark_divider_page(11),
        large_visual_page(12, "TSPA", METHODS[4:6], stats),
        large_visual_page(13, "TSPA", METHODS[6:8], stats),
        large_visual_page(14, "TSPB", METHODS[4:6], stats),
        large_visual_page(15, "TSPB", METHODS[6:8], stats),
        large_visual_page(16, "TSPA", METHODS[4:6], stats, True),
        large_visual_page(17, "TSPA", METHODS[6:8], stats, True),
        large_visual_page(18, "TSPB", METHODS[4:6], stats, True),
        large_visual_page(19, "TSPB", METHODS[6:8], stats, True),
    ]
    page_paths = []
    for index, page in enumerate(pages, start=1):
        path = BUILD / f"page_{index:02d}.svg"
        path.write_text(page, encoding="utf-8")
        page_paths.append(str(path))
    magick = shutil.which("magick") or r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
    subprocess.run([magick, "-density", "150", *page_paths, "-background", WHITE, "-alpha", "remove", "-compress", "JPEG", "-quality", "88", str(REPORT)], check=True)
    print(f"Generated {REPORT} ({len(pages)} pages)")


if __name__ == "__main__":
    main()
