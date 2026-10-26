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
         stroke: str = "none", radius: int = 18) -> str:
    return (f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{radius}" '
            f'fill="{fill}" stroke="{stroke}"/>')


def line(x1: float, y1: float, x2: float, y2: float, stroke: str = GRID, width: int = 1) -> str:
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}"/>'


def page_start(title: str, kicker: str, number: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
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
        text(WIDTH - 70, 1722, f"Lab 02 | {number:02d}", 14, MUTED, anchor="end"),
        "</svg>",
    ])
    return "\n".join(parts)


def table(parts: list[str], x: int, y: int, widths: list[int], headers: list[str], rows: list[list[str]],
          row_height: int = 44, font_size: int = 16) -> None:
    total = sum(widths)
    parts.append(rect(x, y, total, row_height, NAVY, radius=8))
    cursor = x
    for width, header in zip(widths, headers):
        parts.append(text(cursor + width / 2, y + 29, header, font_size, WHITE, "700", anchor="middle"))
        cursor += width
    for row_index, row in enumerate(rows):
        row_y = y + row_height * (row_index + 1)
        parts.append(rect(x, row_y, total, row_height, WHITE if row_index % 2 == 0 else "#eef3f7", radius=0))
        cursor = x
        for width, value in zip(widths, row):
            parts.append(text(cursor + width / 2, row_y + 29, value, font_size, INK, anchor="middle"))
            cursor += width
    parts.append(rect(x, y, total, row_height * (len(rows) + 1), "none", GRID, 8))


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


def read_route(instance: str, method: str) -> list[int]:
    path = EVALUATION / "results" / f"{instance}_{method}.csv"
    return [int(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def route_lines(route: list[int], per_line: int = 28) -> list[str]:
    return [" ".join(str(node) for node in route[i:i + per_line]) for i in range(0, len(route), per_line)]


def render_plot(path: Path) -> Path:
    BUILD.mkdir(exist_ok=True)
    output = BUILD / f"{path.stem}.png"
    if not output.exists() or output.stat().st_mtime < path.stat().st_mtime:
        magick = shutil.which("magick") or r"C:\Program Files\ImageMagick-7.1.1-Q16-HDRI\magick.exe"
        subprocess.run([magick, str(path), "-resize", "320x320", str(output)], check=True)
    return output


def image_data(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def image(parts: list[str], path: Path, x: int, y: int, width: int, height: int) -> None:
    parts.append(f'<image x="{x}" y="{y}" width="{width}" height="{height}" preserveAspectRatio="xMidYMid meet" '
                 f'href="data:image/png;base64,{image_data(render_plot(path))}"/>')


def cover_page(number: int) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{LIGHT}"/>',
        rect(0, 0, WIDTH, 650, NAVY, radius=0),
        '<circle cx="1080" cy="65" r="210" fill="#1f5f8b" opacity="0.36"/>',
        '<circle cx="1120" cy="150" r="125" fill="#2c8c87" opacity="0.42"/>',
        '<circle cx="88" cy="625" r="230" fill="#e98b45" opacity="0.92"/>',
        text(76, 86, "EVOLUTIONARY COMPUTATION", 17, "#b7d0e1", "700"),
        text(76, 160, "LABORATORY 02", 22, ORANGE, "700"),
        text(76, 250, "Greedy", 68, WHITE, "700"),
        text(76, 326, "regret heuristics", 60, WHITE, "700"),
        text(80, 402, "Selecting a subset and arranging it into a low-cost Hamiltonian cycle", 21, "#d9e8f1"),
        rect(76, 470, 420, 70, "#ffffff", radius=35),
        text(112, 515, "ASSIGNMENT 2 - REPORT", 18, WHITE, "700"),
        text(76, 716, "Focus", 18, BLUE, "700"),
        text(76, 760, "2-regret selection", 34, INK, "700"),
        text(76, 800, "and weighted insertion scores", 22, MUTED),
        rect(76, 890, 1088, 260, WHITE, GRID, 22),
        text(112, 950, "CORE OBJECTIVE", 15, TEAL, "700"),
        text(112, 1012, "Minimize cycle length + selected node costs", 32, INK, "700"),
        text(112, 1068, "Every solution selects ceil(n / 2) nodes and closes the route", 20, MUTED),
        text(112, 1102, "with an edge back to the first selected node.", 20, MUTED),
        rect(76, 1220, 520, 190, PALE_BLUE, radius=20),
        text(110, 1270, "INSTANCES", 14, BLUE, "700"),
        text(110, 1324, "TSPA   -   TSPB", 31, INK, "700"),
        text(110, 1370, "200 nodes each - 100 selected", 18, MUTED),
        rect(644, 1220, 520, 190, PALE_TEAL, radius=20),
        text(678, 1270, "EXPERIMENT", 14, TEAL, "700"),
        text(678, 1324, "8 constructive methods", 31, INK, "700"),
        text(678, 1370, "200 evaluated solutions per method", 18, MUTED),
    ]
    return page_end(parts, number)


def problem_page(number: int) -> str:
    parts = page_start("Problem and experimental design", "01 - foundations", number)
    parts.extend([
        text(70, 190, "Each node has integer coordinates and a selection cost.", 24, INK, "700"),
        multiline(70, 238, wrap("The solver chooses k = ceil(n / 2) distinct nodes and orders them into a closed Hamiltonian cycle. Distances are rounded Euclidean distances computed before optimization.", 96), 19, MUTED, line_height=29),
        rect(70, 390, 1100, 112, NAVY, radius=18),
        text(105, 430, "OBJECTIVE FUNCTION", 14, ORANGE, "700"),
        text(105, 477, "F(C) = cycle length(C) + sum of selected node costs", 27, WHITE, "700"),
        rect(70, 548, 525, 300, PALE_BLUE, radius=20),
        rect(645, 548, 525, 300, PALE_TEAL, radius=20),
        text(105, 594, "CONSTRAINTS", 15, BLUE, "700"),
        text(680, 594, "EXPERIMENT", 15, TEAL, "700"),
        multiline(105, 646, ["- select exactly ceil(n / 2) nodes", "- visit each selected node once", "- return to the first node", "- use zero-based indices"], 19, INK, line_height=38),
        multiline(680, 646, ["TSPA and TSPB", "200 nodes / instance", "100 selected nodes", "200 starts / method"], 19, INK, line_height=38),
        text(70, 934, "Recorded outputs", 27, INK, "700"),
        multiline(70, 980, wrap("For every instance and method, the program writes min, max, average, standard deviation, runtime, best and worst routes, and SVG visualizations. Every produced route is checked internally for size, closure, range, and uniqueness.", 100), 19, MUTED, line_height=29),
        text(70, 1200, "Shared representation", 27, INK, "700"),
        rect(70, 1248, 1100, 220, WHITE, GRID, 20),
        multiline(108, 1300, ["Optimization code receives the precomputed distance matrix and node costs.", "Coordinates are used only for distance construction and final 2D visualization.", "This matches the separation required by the problem description."], 19, MUTED, line_height=38),
    ])
    return page_end(parts, number)


def algorithms_page(number: int) -> str:
    parts = page_start("Algorithms and pseudocode", "02 - methods", number)
    parts.append(text(70, 190, "The regret value measures how costly it would be to postpone a node.", 22, MUTED))
    cards = [
        (70, 238, "2-regret on an open path", PALE_BLUE, [
            "path <- [start]",
            "while |path| < k:",
            "  for each unused v:",
            "    evaluate every path insertion",
            "    best <- smallest delta(v)",
            "    second <- second smallest delta(v)",
            "    regret(v) <- second - best",
            "  choose max regret(v)",
            "  insert v at its best position",
        ]),
        (640, 238, "2-regret on a closed cycle", PALE_TEAL, [
            "cycle <- [start, best second node]",
            "while |cycle| < k:",
            "  for each unused v and cycle edge:",
            "    delta <- d(a,v)+d(v,b)-d(a,b)+c(v)",
            "    keep the two best deltas",
            "    regret(v) <- second - best",
            "  choose max regret(v)",
            "  insert v at its best edge",
        ]),
        (70, 910, "Weighted score - path", PALE_ORANGE, [
            "regret(v) <- second(v) - best(v)",
            "score(v) <- wr * regret(v)",
            "              - wd * best(v)",
            "choose the maximum score",
            "default: wr = 1, wd = 1",
            "insert at the best path position",
        ]),
        (640, 910, "Weighted score - cycle", PALE_ORANGE, [
            "regret(v) <- second(v) - best(v)",
            "score(v) <- wr * regret(v)",
            "              - wd * best(v)",
            "choose the maximum score",
            "default: wr = 1, wd = 1",
            "insert at the best cycle edge",
        ]),
    ]
    for x, y, title, fill, code in cards:
        parts.append(rect(x, y, 530, 560, WHITE, GRID, 20))
        parts.append(rect(x, y, 9, 560, TEAL if "cycle" in title else BLUE, radius=5))
        parts.append(text(x + 32, y + 45, title, 22, INK, "700"))
        parts.append(rect(x + 24, y + 78, 482, 438, fill, radius=12))
        parts.append(multiline(x + 48, y + 120, code, 17, INK, family="Consolas", line_height=39))
    parts.extend([
        text(70, 1570, "Insertion delta", 24, INK, "700"),
        multiline(70, 1615, wrap("For both representations, delta includes the change in cycle/path length plus the newly selected node cost. The path variants follow lab 01's open-path insertion convention; cycle variants evaluate closed-cycle edges.", 100), 17, MUTED, line_height=25),
    ])
    return page_end(parts, number)


def results_page(number: int, instance: str, stats: dict[str, list[dict[str, str]]], times: dict[str, dict[str, str]]) -> str:
    parts = page_start(f"Computational experiment - {instance}", "03 - results", number)
    parts.extend([
        text(70, 190, "Each row aggregates 200 solutions generated from all possible starting nodes.", 19, MUTED),
        text(70, 230, "Weighted methods use equal weights: regret_weight = 1 and delta_weight = 1.", 19, MUTED),
        text(70, 310, f"Objective statistics - {instance}", 27, INK, "700"),
    ])
    rows = []
    labels = {method_id: label for method_id, label, _ in METHODS}
    for row in stats[instance]:
        rows.append([labels[row["method_name"]], fmt(row["min"]), fmt(row["max"]), fmt(row["avg"]), fmt(row["sd"])])
    table(parts, 70, 350, [320, 145, 145, 170, 170], ["Method", "Min", "Max", "Average", "Std. dev."], rows, 48, 15)
    best_min = min(stats[instance], key=lambda row: float(row["min"]))
    best_avg = min(stats[instance], key=lambda row: float(row["avg"]))
    parts.extend([
        rect(70, 850, 1100, 250, WHITE, GRID, 20),
        text(108, 902, "Result summary", 24, INK, "700"),
        multiline(108, 950, wrap(f"Best individual solution: {labels[best_min['method_name']]} with objective {fmt(best_min['min'])}.", 88), 19, MUTED, line_height=29),
        multiline(108, 1020, wrap(f"Best average: {labels[best_avg['method_name']]} with average objective {fmt(best_avg['avg'])}.", 88), 19, MUTED, line_height=29),
        text(70, 1190, "Runtime (all 200 solutions)", 25, INK, "700"),
    ])
    runtime_rows = [[labels[key], f"{value} ms"] for key, value in times[instance].items()]
    table(parts, 70, 1235, [560, 300], ["Method", "Runtime"], runtime_rows, 42, 15)
    return page_end(parts, number)


def visual_page(number: int, instance: str, subset: list[tuple[str, str, str]], stats: dict[str, list[dict[str, str]]]) -> str:
    parts = page_start(f"Best solutions - {instance}", "04 - visual inspection", number)
    parts.append(text(70, 160, "Node cost is encoded by colour and size; the polyline is the closed route.", 17, MUTED))
    stat_by_id = {row["method_name"]: row for row in stats[instance]}
    for index, (method_id, label, stem) in enumerate(subset):
        y = 205 + index * 365
        row = stat_by_id[method_id]
        parts.append(rect(70, y, 1100, 335, WHITE, GRID, 18))
        parts.append(text(98, y + 38, label, 20 if len(label) < 28 else 17, INK, "700"))
        parts.append(text(98, y + 70, f"min {fmt(row['min'])} | max {fmt(row['max'])} | avg {fmt(row['avg'])}", 14, MUTED))
        image(parts, EVALUATION / "plots" / f"{instance}_{stem}.svg", 350, y + 10, 310, 310)
        parts.append(text(710, y + 58, "Best route", 16, TEAL, "700"))
        route = read_route(instance, stem)
        parts.append(multiline(710, y + 92, route_lines(route, 22), 11, MUTED, family="Consolas", line_height=16))
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
    parts = page_start("Conclusions", "06 - discussion", number)
    tspa = {row["method_name"]: row for row in stats["TSPA"]}
    tspb = {row["method_name"]: row for row in stats["TSPB"]}
    parts.extend([
        text(70, 190, "Regret changes the selection priority, but its effect depends on the insertion representation.", 20, MUTED),
        rect(70, 280, 1100, 940, WHITE, GRID, 20),
        text(108, 340, "Main findings", 25, INK, "700"),
        multiline(108, 405, wrap(f"On TSPA, weighted regret on the closed cycle obtained the best individual result ({fmt(tspa['weighted_cycle']['min'])}) and the best average among the new methods ({fmt(tspa['weighted_cycle']['avg'])}).", 91), 19, MUTED, line_height=29),
        multiline(108, 545, wrap(f"On TSPB, weighted regret on the open path was strongest: minimum {fmt(tspb['weighted_path']['min'])} and average {fmt(tspb['weighted_path']['avg'])}.", 91), 19, MUTED, line_height=29),
        multiline(108, 685, wrap("Pure 2-regret performs worse on these instances because it prioritizes nodes with a large difference between their first and second insertion choices, even when their best insertion is expensive. The weighted criterion restores pressure toward a low immediate objective change.", 91), 19, MUTED, line_height=29),
        multiline(108, 870, wrap("The open-path and closed-cycle variants behave differently. The cycle variant accounts for every insertion edge in the current closed route, while the path variant follows the extended nearest-neighbor construction used in lab 01.", 91), 19, MUTED, line_height=29),
        multiline(108, 1055, wrap("All 3,200 generated routes passed the internal structural validation: exactly 100 distinct selected nodes, valid indices, and a repeated first node. Saved routes and plots are available in evaluation/.", 91), 19, MUTED, line_height=29),
        rect(70, 1305, 1100, 130, PALE_BLUE, "#b9d6e8", 20),
        text(108, 1350, "NEXT STEP", 15, BLUE, "700"),
        text(108, 1400, "Local search can refine the constructive routes in the next laboratory.", 19, INK, "700"),
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
        visual_page(6, "TSPA", METHODS[:4], stats),
        visual_page(7, "TSPA", METHODS[4:], stats),
        visual_page(8, "TSPB", METHODS[:4], stats),
        visual_page(9, "TSPB", METHODS[4:], stats),
        route_page(10, "TSPA"),
        route_page(11, "TSPB"),
        conclusions_page(12, stats),
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
