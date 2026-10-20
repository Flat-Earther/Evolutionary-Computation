"""Generate the Lab 01 report from the current evaluation artifacts.

The report is intentionally data-driven: later labs can reuse the same page,
table, card, and visualisation helpers while changing only the experiment
data and section content.
"""

from __future__ import annotations

import base64
import csv
import html
import os
import shutil
import subprocess
from pathlib import Path


WIDTH = 1240
HEIGHT = 1754
ROOT = Path(__file__).resolve().parent
EVALUATION = ROOT / "evaluation"
DATA_DIR = ROOT.parent / "problem-description" / "data" / "example"
REPORT_PATH = ROOT / "report.pdf"

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

METHODS = [
    ("random", "Random solution", "random_sol"),
    ("nn_end", "Nearest neighbor — end", "nn_at_end"),
    ("nn_flexible", "Nearest neighbor — flexible", "nn_flexible"),
    ("greedy_cycle", "Greedy cycle", "greedy_cycle"),
]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def fmt(value: float | int) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def clean_number(value: str | float | int) -> str:
    """Format evaluation values without unnecessary trailing zeroes."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def fixed_decimal(value: str | float | int, places: int = 2) -> str:
    """Format a statistic with a fixed number of digits after the decimal point."""
    return f"{float(value):.{places}f}"


REPORT_METHODS = [
    ("random", "Random", "random_sol"),
    ("nn_end", "Nearest Neighbor - End", "nn_at_end"),
    ("nn_flexible", "Nearest Neighbor - Any Position", "nn_flexible"),
    ("greedy_cycle", "Greedy Cycle", "greedy_cycle"),
]


def text(x: float, y: float, value: str, size: int = 20, fill: str = INK,
         weight: str = "400", family: str = "Arial", anchor: str = "start",
         opacity: float = 1.0) -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}px" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" '
        f'opacity="{opacity}">{esc(value)}</text>'
    )


def multiline(x: float, y: float, lines: list[str], size: int = 20, fill: str = INK,
              weight: str = "400", family: str = "Arial", line_height: int | None = None) -> str:
    line_height = line_height or int(size * 1.35)
    tspans = []
    for index, line in enumerate(lines):
        dy = 0 if index == 0 else line_height
        tspans.append(f'<tspan x="{x}" dy="{dy}">{esc(line)}</tspan>')
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}px" '
        f'font-weight="{weight}" fill="{fill}">' + "".join(tspans) + "</text>"
    )


def wrap_words(value: str, max_chars: int) -> list[str]:
    lines: list[str] = []
    for paragraph in value.split("\n"):
        words = paragraph.split()
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if current and len(candidate) > max_chars:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines or [""]


def wrap_tokens(tokens: list[int], max_chars: int = 68) -> list[str]:
    lines: list[str] = []
    current = ""
    for token in tokens:
        candidate = str(token) if not current else current + " " + str(token)
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = str(token)
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def rect(x: float, y: float, width: float, height: float, fill: str = WHITE,
         stroke: str = "none", radius: int = 18, stroke_width: int = 1,
         opacity: float = 1.0) -> str:
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" opacity="{opacity}"/>'
    )


def line(x1: float, y1: float, x2: float, y2: float, stroke: str = GRID,
         width: int = 1, dash: str | None = None) -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}"{dash_attr}/>'


def circle(cx: float, cy: float, radius: float, fill: str, opacity: float = 1.0) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{fill}" opacity="{opacity}"/>'


def magick_executable() -> str:
    executable = shutil.which("magick") or r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
    if not Path(executable).exists() and shutil.which(executable) is None:
        raise RuntimeError("ImageMagick 'magick' executable was not found")
    return executable


def render_plot(path: Path) -> Path:
    """Rasterise a plot once so nested SVG images render in the final PDF."""
    cache_dir = ROOT / ".report-build" / "plot-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    output = cache_dir / f"{path.stem}.png"
    if not output.exists() or output.stat().st_mtime < path.stat().st_mtime:
        subprocess.run([magick_executable(), str(path), "-resize", "800x800", str(output)], check=True)
    return output


def image_data(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    mime = "image/png" if path.suffix.lower() == ".png" else "image/svg+xml"
    return f"data:{mime};base64,{encoded}"


def svg_image(path: Path, x: float, y: float, width: float, height: float) -> str:
    asset = render_plot(path) if path.suffix.lower() == ".svg" else path
    return (
        f'<image x="{x}" y="{y}" width="{width}" height="{height}" '
        f'preserveAspectRatio="xMidYMid meet" xlink:href="{image_data(asset)}"/>'
    )


def page_start(title: str, kicker: str, number: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{LIGHT}"/>',
        rect(0, 0, WIDTH, 126, NAVY, radius=0),
        text(70, 42, kicker.upper(), 14, ORANGE, "700"),
        text(70, 93, title, 34, WHITE, "700"),
        text(WIDTH - 70, 46, "LAB 01", 15, "#b7d0e1", "700", anchor="end"),
        text(WIDTH - 70, 91, f"{number:02d}", 26, WHITE, "700", anchor="end"),
    ]


def page_end(parts: list[str], number: int) -> str:
    parts.extend([
        line(70, 1688, WIDTH - 70, 1688, GRID, 1),
        text(70, 1722, "Evolutionary Computation · Greedy Heuristics", 14, MUTED),
        text(WIDTH - 70, 1722, f"Paweł Świątek · Jędrzej Szmidt   |   {number:02d}", 14, MUTED, anchor="end"),
        "</svg>",
    ])
    return "\n".join(parts)


def cover_page(number: int) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{LIGHT}"/>',
        rect(0, 0, WIDTH, 650, NAVY, radius=0),
        circle(1080, 65, 210, BLUE, 0.36),
        circle(1120, 150, 125, TEAL, 0.42),
        circle(88, 625, 230, ORANGE, 0.92),
        text(76, 86, "EVOLUTIONARY COMPUTATION", 17, "#b7d0e1", "700"),
        text(76, 160, "LABORATORY 01", 22, ORANGE, "700"),
        text(76, 250, "Greedy", 68, WHITE, "700"),
        text(76, 326, "heuristics", 68, WHITE, "700"),
        text(80, 402, "Selecting and arranging a fixed-size subset of nodes", 22, "#d9e8f1"),
        rect(76, 470, 400, 70, "#ffffff", radius=35, opacity=0.12),
        text(112, 515, "ASSIGNMENT 1 · REPORT", 18, WHITE, "700"),
        text(76, 716, "Authors", 18, BLUE, "700"),
        text(76, 760, "Paweł Świątek", 34, INK, "700"),
        text(76, 800, "160301", 20, MUTED),
        text(390, 760, "Jędrzej Szmidt", 34, INK, "700"),
        text(390, 800, "160292", 20, MUTED),
        rect(76, 890, 1088, 260, WHITE, GRID, 22),
        text(112, 950, "CORE OBJECTIVE", 15, TEAL, "700"),
        text(112, 1012, "Minimize cycle length + selected node costs", 32, INK, "700"),
        text(112, 1068, "Every solution selects exactly 50% of the instance nodes, rounded up,", 20, MUTED),
        text(112, 1102, "and forms a Hamiltonian cycle through the selected subset.", 20, MUTED),
        rect(76, 1220, 520, 190, PALE_BLUE, radius=20),
        text(110, 1270, "INSTANCES", 14, BLUE, "700"),
        text(110, 1324, "TSPA   ·   TSPB", 31, INK, "700"),
        text(110, 1370, "200 nodes each · 100 selected", 18, MUTED),
        rect(644, 1220, 520, 190, PALE_TEAL, radius=20),
        text(678, 1270, "METHODS", 14, TEAL, "700"),
        text(678, 1324, "4 constructive strategies", 31, INK, "700"),
        text(678, 1370, "200 evaluated solutions per method", 18, MUTED),
        line(76, 1510, 1164, 1510, GRID, 1),
        text(76, 1565, "Poznań University of Technology · Artificial Intelligence", 17, MUTED),
        text(1164, 1565, "October 2026", 17, MUTED, anchor="end"),
    ]
    return page_end(parts, number)


def card_title(parts: list[str], x: float, y: float, title: str, subtitle: str | None = None,
               accent: str = BLUE) -> None:
    parts.append(text(x, y, title, 23, INK, "700"))
    parts.append(rect(x, y + 14, 48, 5, accent, radius=3))
    if subtitle:
        parts.append(text(x, y + 48, subtitle, 16, MUTED))


def table(parts: list[str], x: float, y: float, widths: list[int], headers: list[str], rows: list[list[str]],
          row_height: int = 42, font_size: int = 16,
          highlight_cells: dict[tuple[int, int], str] | None = None,
          bold_cells: set[tuple[int, int]] | None = None) -> int:
    total_width = sum(widths)
    highlight_cells = highlight_cells or {}
    bold_cells = bold_cells or set()
    parts.append(rect(x, y, total_width, row_height, NAVY, radius=8))
    cursor = x
    for width, header in zip(widths, headers):
        parts.append(text(cursor + width / 2, y + row_height / 2 + font_size * 0.35,
                          header, font_size, WHITE, "700", anchor="middle"))
        cursor += width
    for row_index, row in enumerate(rows):
        row_y = y + row_height * (row_index + 1)
        fill = WHITE if row_index % 2 == 0 else "#eef3f7"
        parts.append(rect(x, row_y, total_width, row_height, fill, radius=0))
        cursor = x
        for column_index, (width, value) in enumerate(zip(widths, row)):
            cell = (row_index, column_index)
            if cell in highlight_cells:
                parts.append(rect(cursor + 3, row_y + 3, width - 6, row_height - 6,
                                  highlight_cells[cell], radius=6))
            weight = "700" if cell in bold_cells else "400"
            cell_font_size = font_size + 4 if cell in bold_cells else font_size
            parts.append(text(cursor + width / 2, row_y + row_height / 2 + cell_font_size * 0.35,
                              value, cell_font_size, INK, weight, anchor="middle"))
            cursor += width
    parts.append(rect(x, y, total_width, row_height * (len(rows) + 1), "none", GRID, 8, 1))
    return row_height * (len(rows) + 1)


def code_card(parts: list[str], x: int, y: int, width: int, height: int, title: str,
             description: str, code: list[str], accent: str) -> None:
    parts.append(rect(x, y, width, height, WHITE, GRID, 20))
    parts.append(rect(x, y, 9, height, accent, radius=5))
    parts.append(text(x + 32, y + 43, title, 24, INK, "700"))
    description_lines = wrap_words(description, 45)
    parts.append(multiline(x + 32, y + 78, description_lines, 16, MUTED, line_height=23))
    code_y = y + 148
    code_height = height - 172
    parts.append(rect(x + 24, code_y, width - 48, code_height, NAVY, radius=12))
    parts.append(multiline(x + 44, code_y + 34, code, 15, "#e2eef5", family="Consolas", line_height=24))


def read_stats() -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = {}
    for instance in ("TSPA", "TSPB"):
        with (EVALUATION / f"{instance}_stats.csv").open(newline="", encoding="utf-8") as handle:
            result[instance] = list(csv.DictReader(handle))
    return result


def read_times() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for instance in ("TSPA", "TSPB"):
        with (EVALUATION / f"{instance}_times.csv").open(newline="", encoding="utf-8") as handle:
            result[instance] = {row["method_name"]: row["time"] for row in csv.DictReader(handle)}
    return result


def read_nodes(instance: str) -> list[tuple[int, int, int]]:
    nodes = []
    with (DATA_DIR / f"{instance}.csv").open(encoding="utf-8") as handle:
        for row in csv.reader(handle, delimiter=";"):
            if row:
                nodes.append((int(row[0]), int(row[1]), int(row[2])))
    return nodes


def read_route(instance: str, method: str, worst: bool = False) -> list[int]:
    suffix = "_worst" if worst else ""
    path = EVALUATION / "results" / f"{instance}_{method}{suffix}.csv"
    return [int(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_objectives(stats: dict[str, list[dict[str, str]]]) -> dict[tuple[str, str], tuple[str, str]]:
    result = {}
    for instance, rows in stats.items():
        for row in rows:
            result[(instance, row["method_name"])] = (row["min"], row["max"])
    return result


def task_page(number: int) -> str:
    parts = page_start("Problem and experimental design", "01 · foundations", number)
    parts.extend([
        text(70, 190, "What is being optimized?", 27, INK, "700"),
        multiline(70, 234, wrap_words(
            "Each instance contains nodes with integer coordinates and a selection cost. "
            "The solver must choose a fixed-size subset and order it into a Hamiltonian cycle. "
            "The optimization methods use the precomputed distance matrix and node costs.", 89), 19, MUTED, line_height=29),
        rect(70, 390, 1100, 112, NAVY, radius=18),
        text(105, 430, "OBJECTIVE FUNCTION", 14, ORANGE, "700"),
        text(105, 477, "F(C) = total cycle length + total cost of selected nodes", 27, WHITE, "700"),
        rect(70, 548, 525, 300, PALE_BLUE, radius=20),
        rect(645, 548, 525, 300, PALE_TEAL, radius=20),
        text(105, 594, "CONSTRAINTS", 15, BLUE, "700"),
        text(680, 594, "DISTANCES", 15, TEAL, "700"),
        multiline(105, 646, [
            "• select ceil(n / 2) nodes",
            "• visit every selected node once",
            "• return to the first node",
            "• node indices start at 0",
        ], 20, INK, line_height=38),
        multiline(680, 646, [
            "Euclidean distance",
            "rounded mathematically",
            "to an integer before",
            "optimization begins.",
        ], 20, INK, line_height=38),
        text(70, 934, "Experimental setup", 27, INK, "700"),
    ])
    table(parts, 70, 978, [190, 180, 190, 280], ["Instance", "Nodes", "Selected", "Runs / method"], [
        ["TSPA", "200", "100", "200 (one per start node)"],
        ["TSPB", "200", "100", "200 (one per start node)"],
    ], row_height=48, font_size=17)
    parts.extend([
        text(70, 1168, "Verification and implementation", 27, INK, "700"),
        rect(70, 1215, 1100, 250, WHITE, GRID, 20),
        text(106, 1260, "Implementation", 16, BLUE, "700"),
        multiline(106, 1302, wrap_words(
            "C++17 implementation using standard library containers and a precomputed symmetric distance matrix. "
            "The four methods are evaluated on both supplied instances.", 80), 18, MUTED, line_height=28),
        text(106, 1392, "Solution checker", 16, TEAL, "700"),
        multiline(106, 1434, wrap_words(
            "All generated solutions were checked against the provided solution checker, including the saved best "
            "and worst solutions reported in this document.", 80), 18, MUTED, line_height=28),
    ])
    return page_end(parts, number)


def algorithms_page_one(number: int) -> str:
    parts = page_start("Algorithms I — baseline constructions", "02 · methods", number)
    parts.append(text(70, 190, "The move is selected by objective impact, not distance alone.", 22, MUTED))
    code_card(parts, 70, 238, 530, 610, "Random solution", "A baseline that samples a valid subset and randomizes its cyclic order.", [
        "all_nodes <- [0, 1, ..., n - 1]",
        "shuffle(all_nodes)",
        "route <- first ceil(n / 2) nodes",
        "append route[0] to close the cycle",
        "return route and F(route)",
    ], ORANGE)
    code_card(parts, 640, 238, 530, 610, "Nearest neighbor — end", "Builds a path by appending the best unused node to the current end.", [
        "path <- [start]",
        "while |path| < k:",
        "  for each unused node v:",
        "    delta <- d(last, v) + cost(v)",
        "  v* <- argmin(delta)",
        "  append v* to path",
        "close path and evaluate F(path)",
    ], BLUE)
    parts.extend([
        text(70, 932, "Shared decision rule", 25, INK, "700"),
        rect(70, 978, 1100, 210, PALE_ORANGE, radius=20),
        text(108, 1032, "At every step", 17, ORANGE, "700"),
        multiline(108, 1074, wrap_words(
            "candidate changes are compared using the change in the complete objective: "
            "distance contribution plus the cost of the newly selected node. This makes the methods adapted "
            "to the assignment rather than literal geometric nearest-neighbor rules.", 90), 20, INK, line_height=31),
        text(70, 1300, "Complexity intuition", 25, INK, "700"),
        multiline(70, 1346, wrap_words(
            "The append-only method evaluates unused nodes at one position. The insertion-based methods evaluate "
            "multiple positions and therefore require more computation, but can produce better cycles.", 100), 19, MUTED, line_height=29),
    ])
    return page_end(parts, number)


def algorithms_page_two(number: int) -> str:
    parts = page_start("Algorithms II — insertion constructions", "02 · methods", number)
    parts.append(text(70, 190, "Both methods evaluate the complete candidate insertion delta.", 22, MUTED))
    code_card(parts, 70, 238, 530, 650, "Nearest neighbor — flexible", "Builds an open path and allows insertion at the beginning, end, or any internal gap.", [
        "path <- [start]",
        "while |path| < k:",
        "  for each unused v:",
        "    evaluate beginning and end",
        "    evaluate every internal gap",
        "    delta includes cost(v)",
        "  apply the best global insertion",
        "close with path[0]",
    ], TEAL)
    code_card(parts, 640, 238, 530, 650, "Greedy cycle", "Maintains a closed cycle and inserts the best unused node into the best cycle edge.", [
        "cycle <- [start, best second node]",
        "while |cycle| < k:",
        "  for each unused v and edge (a, b):",
        "    delta <- d(a,v) + d(v,b)",
        "             - d(a,b) + cost(v)",
        "  insert the best (v, edge)",
        "return closed cycle and F(cycle)",
    ], BLUE)
    parts.extend([
        text(70, 972, "Why the two insertion methods differ", 25, INK, "700"),
        rect(70, 1020, 1100, 250, WHITE, GRID, 20),
        text(108, 1070, "Flexible path", 18, TEAL, "700"),
        text(662, 1070, "Greedy cycle", 18, BLUE, "700"),
        multiline(108, 1116, wrap_words("The two ends are open while the path is being built. A beginning or end insertion can change the eventual closing edge.", 43), 18, MUTED, line_height=28),
        multiline(662, 1116, wrap_words("The closing edge is always part of the current cycle, so every candidate is evaluated against every cycle edge.", 43), 18, MUTED, line_height=28),
        text(70, 1370, "The distinction is visible in the results: the flexible and greedy-cycle solution spaces are no longer identical.", 19, INK, "700"),
    ])
    return page_end(parts, number)


def results_page(number: int, stats: dict[str, list[dict[str, str]]], times: dict[str, dict[str, str]]) -> str:
    parts = page_start("Results at a glance", "03 · experiment", number)
    parts.append(text(70, 190, "Each value is the objective F(C); lower is better.", 22, MUTED))
    for index, instance in enumerate(("TSPA", "TSPB")):
        x = 70 + index * 570
        parts.append(rect(x, 240, 530, 505, WHITE, GRID, 20))
        parts.append(text(x + 32, 286, instance, 27, INK, "700"))
        parts.append(text(x + 32, 318, "200 evaluated solutions per method", 16, MUTED))
        rows = []
        for row in stats[instance]:
            rows.append([
                {"random_sol": "Random", "nn_at_end": "NN end", "nn_flexible": "NN flexible", "greedy_cycle": "Greedy cycle"}[row["method_name"]],
                row["min"], row["max"], row["avg"], row["sd"],
            ])
        table(parts, x + 24, 350, [142, 84, 84, 104, 78], ["Method", "Min", "Max", "Average", "SD"], rows, row_height=48, font_size=14)
        parts.append(text(x + 32, 710, "Runtime (ms)", 15, BLUE, "700"))
        runtime = []
        for _, label, key in METHODS:
            runtime.append(f"{label}: {times[instance][key]} ms")
        parts.append(multiline(x + 32, 737, runtime, 15, MUTED, line_height=22))
    best_rows = []
    labels = {key: label for _, label, key in METHODS}
    for instance in ("TSPA", "TSPB"):
        best = min(stats[instance], key=lambda row: float(row["avg"]))
        best_rows.append([
            instance,
            labels[best["method_name"]],
            best["avg"],
            best["min"],
        ])

    parts.extend([
        text(70, 852, "Main observations", 27, INK, "700"),
        rect(70, 900, 1100, 310, PALE_BLUE, radius=20),
        text(108, 954, "1", 26, BLUE, "700"),
        multiline(160, 952, wrap_words("Greedy constructions are dramatically better than random selection on both instances.", 82), 19, INK, line_height=29),
        text(108, 1030, "2", 26, TEAL, "700"),
        multiline(160, 1028, wrap_words("The flexible insertion heuristic and greedy cycle now produce different statistics, as required by their different partial-solution models.", 82), 19, INK, line_height=29),
        text(108, 1120, "3", 26, ORANGE, "700"),
        multiline(160, 1118, wrap_words("Flexible insertion is more computationally expensive than append-only nearest neighbor because it evaluates many more candidate positions.", 82), 19, INK, line_height=29),
        text(70, 1330, "Best average by instance", 25, INK, "700")
    ])
    table(parts, 70, 1372, [220, 220, 220, 220], ["Instance", "Method", "Average", "Minimum"], best_rows, row_height=48, font_size=16)
    return page_end(parts, number)


def visual_page(number: int, instance: str, stats: dict[str, list[dict[str, str]]], worst: bool = False) -> str:
    title = f"{instance} — {'worst' if worst else 'best'} solutions"
    parts = page_start(title, "04 · visual analysis", number)
    parts.append(text(70, 160, "Node colour and size indicate node cost; the dark line is the selected cycle.", 17, MUTED))
    image_width = 320
    row_height = 365
    start_y = 208
    for index, (method, label, stat_key) in enumerate(METHODS):
        y = start_y + index * row_height
        parts.append(rect(70, y, 1100, 338, WHITE, GRID, 18))
        parts.append(text(98, y + 38, label, 20, INK, "700"))
        parts.append(text(98, y + 68, "worst route" if worst else "best route", 15, MUTED))
        stat_row = next(row for row in stats[instance] if row["method_name"] == stat_key)
        objective = stat_row["max"] if worst else stat_row["min"]
        parts.append(rect(98, y + 100, 178, 38, PALE_ORANGE if worst else PALE_TEAL, radius=19))
        parts.append(text(187, y + 126, f"objective {objective}", 14, INK, "700", anchor="middle"))
        plot = EVALUATION / "plots" / f"{instance}_{method}{'_worst' if worst else ''}.svg"
        parts.append(svg_image(plot, 350, y + 18, image_width, image_width))
        route = read_route(instance, method, worst)
        parts.append(text(710, y + 54, "Stored node-index route", 15, BLUE, "700"))
        parts.append(multiline(710, y + 88, wrap_tokens(route, 49)[:10], 13, MUTED, family="Consolas", line_height=20))
        parts.append(text(710, y + 300, f"{len(set(route[:-1]))} unique selected nodes · closed route", 14, TEAL, "700"))
    return page_end(parts, number)


def routes_page(number: int, instance: str, worst: bool = False) -> str:
    title = f"{instance} — {'worst' if worst else 'best'} route lists"
    parts = page_start(title, "05 · reproducibility appendix", number)
    parts.append(text(70, 160, "Routes are listed using zero-based node indices; the first node is repeated at the end to show closure.", 17, MUTED))
    positions = [(70, 218), (640, 218), (70, 910), (640, 910)]
    for (method, label, _), (x, y) in zip(METHODS, positions):
        route = read_route(instance, method, worst)
        parts.append(rect(x, y, 530, 620, WHITE, GRID, 18))
        parts.append(text(x + 26, y + 40, label, 20, INK, "700"))
        parts.append(text(x + 26, y + 69, f"{len(set(route[:-1]))} selected nodes · {len(route)} entries including closure", 14, MUTED))
        parts.append(rect(x + 22, y + 96, 486, 496, NAVY, radius=12))
        parts.append(multiline(x + 42, y + 132, wrap_tokens(route, 58), 13, "#e4eff5", family="Consolas", line_height=22))
    return page_end(parts, number)


def conclusion_page(number: int) -> str:
    parts = page_start("Conclusions and reproducibility", "06 · closing remarks", number)
    parts.extend([
        text(70, 190, "What this experiment shows", 28, INK, "700"),
        rect(70, 236, 1100, 330, WHITE, GRID, 20),
        text(108, 290, "Greedy information matters", 21, BLUE, "700"),
        multiline(108, 334, wrap_words("Random selection has a much wider and worse objective distribution. Using local objective changes to choose nodes produces substantially shorter and cheaper cycles.", 88), 19, MUTED, line_height=29),
        text(108, 428, "The construction model matters", 21, TEAL, "700"),
        multiline(108, 472, wrap_words("NN flexible and greedy cycle are related insertion heuristics, but they evaluate different partial solutions. The corrected implementation produces distinct solution spaces and results.", 88), 19, MUTED, line_height=29),
        text(70, 672, "Practical takeaways", 28, INK, "700"),
        rect(70, 720, 520, 330, PALE_BLUE, radius=20),
        rect(650, 720, 520, 330, PALE_TEAL, radius=20),
        text(106, 770, "Strengths", 18, BLUE, "700"),
        multiline(106, 818, [
            "• simple and interpretable",
            "• valid solutions by construction",
            "• objective-aware node selection",
            "• reusable distance-matrix interface",
        ], 19, INK, line_height=38),
        text(686, 770, "Limitations", 18, TEAL, "700"),
        multiline(686, 818, [
            "• greedy choices are irreversible",
            "• insertion methods are expensive",
            "• no local improvement phase",
            "• random results vary by run",
        ], 19, INK, line_height=38),
        text(70, 1152, "Reproducibility", 28, INK, "700"),
        rect(70, 1200, 1100, 280, WHITE, GRID, 20),
        multiline(108, 1250, wrap_words("The report is generated from the CSV statistics, route lists, and SVG visualisations stored in the evaluation directory. The same report generator can be reused for later laboratories by replacing the experiment data and method descriptions.", 90), 19, MUTED, line_height=29),
        text(108, 1394, "Source code: lab-01-greedy-heuristics/src/", 17, BLUE, "700"),
        text(108, 1434, "Evaluation artifacts: lab-01-greedy-heuristics/evaluation/", 17, BLUE, "700"),
    ])
    return page_end(parts, number)


# The pages below follow the concise structure of report_temp.pdf.  The older
# page builders remain above as reusable design primitives, while this section
# defines the current report layout and wording.
AUTHOR_ONE = "Pawe" + chr(0x142) + " " + chr(0x15a) + "wi" + chr(0x105) + "tek"
AUTHOR_TWO = "J" + chr(0x119) + "drzej Szmidt"
REPOSITORY_URL = "https://github.com/Flat-Earther/Evolutionary-Computation/tree/main/lab-01-greedy-heuristics"


def page_end_friend(parts: list[str], number: int) -> str:
    parts.extend([
        line(70, 1688, WIDTH - 70, 1688, GRID, 1),
        text(70, 1722, "Evolutionary Computation - Greedy Heuristics", 14, MUTED),
        text(WIDTH - 70, 1722, f"{AUTHOR_ONE} - {AUTHOR_TWO}   |   {number:02d}", 14, MUTED, anchor="end"),
        "</svg>",
    ])
    return "\n".join(parts)


def friend_cover_page(number: int) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{LIGHT}"/>',
        rect(0, 0, WIDTH, 650, NAVY, radius=0),
        circle(1080, 65, 210, BLUE, 0.36),
        circle(1120, 150, 125, TEAL, 0.42),
        circle(88, 625, 230, ORANGE, 0.92),
        text(76, 86, "EVOLUTIONARY COMPUTATION", 17, "#b7d0e1", "700"),
        text(76, 160, "LABORATORY 01", 22, ORANGE, "700"),
        text(76, 250, "Greedy", 66, WHITE, "700"),
        text(76, 326, "heuristics", 66, WHITE, "700"),
        text(80, 402, "for the Traveling Salesperson Problem with Node Costs", 20, "#d9e8f1"),
        rect(76, 470, 400, 70, "#ffffff", radius=35, opacity=0.12),
        text(112, 515, "ASSIGNMENT 1 - REPORT", 18, WHITE, "700"),
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
        text(110, 1370, "200 nodes each   -   100 selected", 18, MUTED),
        rect(644, 1220, 520, 190, PALE_TEAL, radius=20),
        text(678, 1270, "METHODS", 14, TEAL, "700"),
        text(678, 1324, "4 greedy and baseline methods", 29, INK, "700"),
        text(678, 1370, "200 solutions evaluated per method", 18, MUTED),
        line(76, 1510, 1164, 1510, GRID, 1),
        text(76, 1565, "Poznan University of Technology - Artificial Intelligence", 17, MUTED),
        text(1164, 1565, "October 2026", 17, MUTED, anchor="end"),
    ]
    return page_end_friend(parts, number)


def friend_problem_page(number: int) -> str:
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
        multiline(70, 946, wrap_words(
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
    return page_end_friend(parts, number)


def friend_algorithms_page_one(number: int) -> str:
    parts = page_start("2. Algorithms and pseudocode", "02 - algorithms", number)
    code_card(parts, 70, 180, 530, 660, "2.1 Random solution", "Randomly selects the required number of distinct nodes. It is used as a baseline.", [
        "Algorithm RandomSolution(n, k)",
        "1. V <- {0, 1, ..., n - 1}",
        "2. S <- randomly select k distinct nodes from V",
        "3. Return S",
        "",
        "The cycle is closed when F(S) is evaluated.",
    ], ORANGE)
    code_card(parts, 640, 180, 530, 660, "2.2 Nearest Neighbor - End", "Starts with one node and repeatedly appends the most promising unused node to the path end.", [
        "Algorithm NearestNeighborEnd(D, C, start)",
        "1. V <- {0, 1, ..., n - 1}",
        "2. S <- [start]; U <- V \\ {start}",
        "3. k <- ceil(n / 2)",
        "4. While |S| < k:",
        "   best <- argmin over v in U:",
        "            D[last][v] + C[v]",
        "   append best to S; remove best from U",
        "5. Return S",
    ], BLUE)
    code_card(parts, 70, 870, 530, 660, "2.3 Nearest Neighbor - Any Position", "Maintains an open path and tests insertion at its beginning, end, and between adjacent nodes.", [
        "Algorithm NearestNeighborAnyPosition(D, C, start)",
        "1. S <- [start]; U <- V \\ {start}",
        "2. k <- ceil(n / 2)",
        "3. While |S| < k:",
        "   For each v in U:",
        "     test beginning: D[v][S[0]] + C[v]",
        "     test end: D[S[-1]][v] + C[v]",
        "     test each gap (a,b):",
        "       D[a][v] + D[v][b] - D[a][b] + C[v]",
        "   insert the best node at the best position",
        "   remove the node from U",
        "4. Return S",
    ], TEAL)
    code_card(parts, 640, 870, 530, 660, "2.4 Greedy Cycle", "Maintains a closed cycle and inserts the best unused node into the best cycle edge.", [
        "Algorithm GreedyCycle(D, C, start)",
        "1. S <- [start]; U <- V \\ {start}",
        "2. k <- ceil(n / 2)",
        "3. second <- argmin over v in U:",
        "      2 * D[start][v] + C[v]",
        "4. S <- [start, second]; remove second from U",
        "5. While |S| < k:",
        "   for each v in U and closed edge (a,b):",
        "     delta <- D[a][v] + D[v][b]",
        "              - D[a][b] + C[v]",
        "   insert the best node and remove it from U",
        "6. Return S",
    ], BLUE)
    return page_end_friend(parts, number)


def friend_stats_rows(stats: dict[str, list[dict[str, str]]], instance: str) -> list[list[str]]:
    labels = {key: label for _, label, key in REPORT_METHODS}
    rows = []
    for row in stats[instance]:
        rows.append([
            labels[row["method_name"]],
            clean_number(row["min"]),
            clean_number(row["max"]),
            fixed_decimal(row["avg"]),
            fixed_decimal(row["sd"]),
        ])
    return rows


def friend_results_page(number: int, instance: str, stats: dict[str, list[dict[str, str]]], times: dict[str, dict[str, str]], final_results: bool = False) -> str:
    parts = page_start(f"3. Computational experiment - {instance}", "03 - experiment", number)
    parts.extend([
        text(70, 190, "The experimental procedure consists of generating 200 solutions for each algorithm and instance.", 19, MUTED),
        text(70, 230, "For the greedy methods, solutions are constructed from different starting nodes; Random uses independent samples.", 19, MUTED),
        text(70, 270, "For each method, minimum, maximum, average, and standard deviation are calculated.", 19, MUTED),
        text(70, 350, f"Experimental results - {instance}", 27, INK, "700"),
    ])
    rows = friend_stats_rows(stats, instance)
    minimum_index = min(range(len(stats[instance])), key=lambda index: float(stats[instance][index]["min"]))
    average_index = min(range(len(stats[instance])), key=lambda index: float(stats[instance][index]["avg"]))
    table(parts, 70, 398, [380, 160, 160, 220, 180],
          ["Algorithm", "Minimum", "Maximum", "Average", "Std. dev."], rows,
          row_height=54, font_size=17,
          highlight_cells={(minimum_index, 1): "#f4a261", (average_index, 3): "#ffd166"},
          bold_cells={(minimum_index, 1), (average_index, 3)})
    instance_rows = {row["method_name"]: row for row in stats[instance]}
    any_row = instance_rows["nn_flexible"]
    best_avg = min(stats[instance], key=lambda row: float(row["avg"]))
    parts.extend([
        rect(70, 700, 1100, 30, "none", "none", 0),
        rect(70, 700, 18, 18, "#f4a261", radius=4),
        text(98, 715, "lowest minimum", 14, MUTED),
        rect(242, 700, 18, 18, "#ffd166", radius=4),
        text(270, 715, "lowest average", 14, MUTED),
        text(70, 770, "Result summary", 25, INK, "700"),
        rect(70, 818, 1100, 285, WHITE, GRID, 20),
        multiline(108, 874, wrap_words(
            f"The best individual solution for {instance} was found by Nearest Neighbor - Any Position, "
            f"with objective {clean_number(any_row['min'])}.", 86), 19, MUTED, line_height=29),
        multiline(108, 966, wrap_words(
            f"The best average result for this instance was obtained by {REPORT_METHODS[[key for _, _, key in REPORT_METHODS].index(best_avg['method_name'])][1]}, "
            f"with average objective {clean_number(best_avg['avg'])}.", 86), 19, MUTED, line_height=29),
        text(108, 1060, "All solutions were checked with the provided solution checker.", 19, INK, "700"),
        text(70, 1170, "Runtime reference", 25, INK, "700"),
        multiline(70, 1218, [
            f"Random: {clean_number(times[instance]['random_sol'])} ms     |     Nearest Neighbor - End: {clean_number(times[instance]['nn_at_end'])} ms",
            f"Nearest Neighbor - Any Position: {clean_number(times[instance]['nn_flexible'])} ms     |     Greedy Cycle: {clean_number(times[instance]['greedy_cycle'])} ms",
        ], 18, MUTED, line_height=31),
    ])
    if final_results:
        parts.append(text(70, 1430, "The following pages present the best solutions and their node-index lists.", 19, INK, "700"))
    return page_end_friend(parts, number)


def friend_visual_page(number: int, instance: str, stats: dict[str, list[dict[str, str]]], worst: bool = False) -> str:
    section = "6 - worst solutions" if worst else "4 - best solutions"
    title = f"{section.split(' - ')[0]}. {'Worst' if worst else 'Best'} solutions - {instance}"
    parts = page_start(title, section, number)
    parts.append(text(70, 160, "The plots show node cost using colour and size. The line represents the closed cycle.", 17, MUTED))
    image_width = 320
    row_height = 365
    start_y = 208
    labels = {key: label for _, label, key in REPORT_METHODS}
    for index, (method, label, stat_key) in enumerate(REPORT_METHODS):
        y = start_y + index * row_height
        parts.append(rect(70, y, 1100, 338, WHITE, GRID, 18))
        label_size = 14 if len(label) > 25 else 19
        parts.append(text(98, y + 36, label, label_size, INK, "700"))
        row = next(item for item in stats[instance] if item["method_name"] == stat_key)
        objective = row["max"] if worst else row["min"]
        parts.append(text(98, y + 66, f"min={clean_number(row['min'])}  max={clean_number(row['max'])}  avg={clean_number(row['avg'])}", 14, MUTED))
        parts.append(rect(98, y + 92, 178, 38, PALE_ORANGE if worst else PALE_TEAL, radius=19))
        parts.append(text(187, y + 118, f"{'worst' if worst else 'best'} = {clean_number(objective)}", 14, INK, "700", anchor="middle"))
        plot = EVALUATION / "plots" / f"{instance}_{method}{'_worst' if worst else ''}.svg"
        parts.append(svg_image(plot, 350, y + 18, image_width, image_width))
        parts.append(text(710, y + 52, f"{'Worst' if worst else 'Best'} solution nodes:", 15, BLUE, "700"))
        route = read_route(instance, method, worst)
        parts.append(multiline(710, y + 86, wrap_tokens(route, 49), 12, MUTED, family="Consolas", line_height=18))
    return page_end_friend(parts, number)


def dark_divider_page(number: int) -> str:
    """Create a dark visual separator before the large-format appendix."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">'
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{NAVY}"/>'
        "</svg>"
    )


def friend_large_visual_page(number: int, instance: str, stats: dict[str, list[dict[str, str]]],
                             worst: bool, pair_index: int) -> str:
    """Show two large plots per page for projection-friendly viewing."""
    mode = "Worst" if worst else "Best"
    accent = ORANGE if worst else TEAL
    background = "#ffe8d8" if worst else "#def2ec"
    border = "#e4a06f" if worst else "#8ac5b6"
    subset = REPORT_METHODS[pair_index * 2:(pair_index + 1) * 2]
    parts = page_start(
        f"7. Large {mode.lower()} visualizations - {instance}",
        f"appendix - {mode.lower()} solutions",
        number,
    )
    card_y = [155, 915]
    for y, (method, label, stat_key) in zip(card_y, subset):
        row = next(item for item in stats[instance] if item["method_name"] == stat_key)
        objective = row["max"] if worst else row["min"]
        route = read_route(instance, method, worst)
        parts.append(rect(70, y, 1100, 740, background, border, 22))
        parts.append(rect(810, y + 24, 224, 40, accent, radius=20))
        parts.append(text(922, y + 50, f"{mode.upper()} SOLUTION", 14, WHITE, "700", anchor="middle"))
        label_size = 18 if len(label) > 25 else 22
        parts.append(text(810, y + 98, label, label_size, INK, "700"))
        parts.append(multiline(810, y + 126, [
            f"minimum {clean_number(row['min'])}",
            f"maximum {clean_number(row['max'])}",
            f"average {fixed_decimal(row['avg'])}",
        ], 12, MUTED, line_height=18))
        parts.append(rect(810, y + 188, 210, 40, WHITE, border, 12))
        parts.append(text(915, y + 215, f"objective {clean_number(objective)}", 14, INK, "700", anchor="middle"))
        plot = EVALUATION / "plots" / f"{instance}_{method}{'_worst' if worst else ''}.svg"
        parts.append(svg_image(plot, 85, y + 25, 700, 700))
        parts.append(text(810, y + 270, f"{mode} solution nodes", 16, accent, "700"))
        parts.append(multiline(810, y + 306, wrap_tokens(route, 38), 12, INK, family="Consolas", line_height=18))
        parts.append(text(810, y + 690, f"{len(set(route[:-1]))} selected nodes; closed route", 14, accent, "700"))
    return page_end_friend(parts, number)


def friend_conclusion_page(number: int, stats: dict[str, list[dict[str, str]]]) -> str:
    parts = page_start("5. Conclusions", "05 - conclusions", number)
    tspa = {row["method_name"]: row for row in stats["TSPA"]}
    tspb = {row["method_name"]: row for row in stats["TSPB"]}
    parts.extend([
        text(70, 190, "The experimental results show that the greedy algorithms outperform the Random Solution method.", 20, MUTED),
        text(70, 230, "Randomly selecting nodes produces inefficient routes with many long and crossing connections.", 20, MUTED),
        rect(70, 310, 1100, 900, WHITE, GRID, 20),
        text(108, 370, "Main conclusions", 25, INK, "700"),
        multiline(108, 430, wrap_words(
            f"Nearest Neighbor - Any Position achieved the best individual solution on both instances: "
            f"{clean_number(tspa['nn_flexible']['min'])} for TSPA and {clean_number(tspb['nn_flexible']['min'])} for TSPB.", 92), 19, MUTED, line_height=29),
        multiline(108, 544, wrap_words(
            f"The best average result depends on the instance. For TSPA, Greedy Cycle obtained the lowest average "
            f"objective ({clean_number(tspa['greedy_cycle']['avg'])}). For TSPB, Nearest Neighbor - End obtained the lowest average "
            f"objective ({clean_number(tspb['nn_at_end']['avg'])}).", 92), 19, MUTED, line_height=29),
        multiline(108, 704, wrap_words(
            "The visualizations show that Random Solution produces routes with many long and crossing edges, while "
            "the greedy methods generally produce more compact cycles by considering distance and node costs during construction.", 92), 19, MUTED, line_height=29),
        multiline(108, 858, wrap_words(
            "Allowing insertion at different positions can improve the best solution found, although it does not always "
            "guarantee the best average performance. The greedy methods make irreversible local decisions and therefore "
            "do not guarantee the global optimum.", 92), 19, MUTED, line_height=29),
        multiline(108, 1012, wrap_words(
            "The obtained solutions provide a useful starting point for more advanced methods, such as local search, "
            "which could further improve route quality.", 92), 19, MUTED, line_height=29),
        rect(70, 1305, 1100, 130, PALE_BLUE, "#b9d6e8", 20),
        text(108, 1350, "SOURCE REPOSITORY", 15, BLUE, "700"),
        text(108, 1400, REPOSITORY_URL, 18, INK, "700"),
        text(70, 1480, "The worst solutions are presented in the final section as an additional comparison.", 17, INK, "700"),
    ])
    return page_end_friend(parts, number)


def generate() -> None:
    stats = read_stats()
    times = read_times()
    temp_dir = ROOT / ".report-build"
    keep_pages = os.environ.get("KEEP_REPORT_PAGES") == "1"
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    pages = [
        friend_cover_page(1),
        friend_problem_page(2),
        friend_algorithms_page_one(3),
        friend_results_page(4, "TSPA", stats, times),
        friend_results_page(5, "TSPB", stats, times, True),
        friend_visual_page(6, "TSPA", stats, False),
        friend_visual_page(7, "TSPB", stats, False),
        friend_conclusion_page(8, stats),
        friend_visual_page(9, "TSPA", stats, True),
        friend_visual_page(10, "TSPB", stats, True),
        dark_divider_page(11),
        friend_large_visual_page(12, "TSPA", stats, False, 0),
        friend_large_visual_page(13, "TSPA", stats, False, 1),
        friend_large_visual_page(14, "TSPB", stats, False, 0),
        friend_large_visual_page(15, "TSPB", stats, False, 1),
        friend_large_visual_page(16, "TSPA", stats, True, 0),
        friend_large_visual_page(17, "TSPA", stats, True, 1),
        friend_large_visual_page(18, "TSPB", stats, True, 0),
        friend_large_visual_page(19, "TSPB", stats, True, 1),
    ]

    try:
        page_paths = []
        for index, page in enumerate(pages, start=1):
            path = temp_dir / f"page_{index:02d}.svg"
            path.write_text(page, encoding="utf-8")
            page_paths.append(str(path))

        command = [
            magick_executable(), "-density", "150", *page_paths,
            "-background", WHITE, "-alpha", "remove",
            "-compress", "JPEG", "-quality", "88", str(REPORT_PATH),
        ]
        subprocess.run(command, check=True)
        print(f"Generated {REPORT_PATH} ({len(pages)} pages)")
    finally:
        if not keep_pages:
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            print(f"Kept intermediate pages in {temp_dir}")


if __name__ == "__main__":
    generate()
