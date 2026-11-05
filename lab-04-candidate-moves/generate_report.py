"""Generate the Lab 04 candidate-moves report."""

from __future__ import annotations

import base64
import csv
import html
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EVALUATION = ROOT / "evaluation"
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
BEST_SCORE = "#ffd166"
BEST_TIME = "#9bd8c9"

AUTHOR_ONE = "Pawe" + chr(0x142) + " " + chr(0x15a) + "wi" + chr(0x105) + "tek"
AUTHOR_TWO = "J" + chr(0x119) + "drzej Szmidt"
REPOSITORY_URL = "https://github.com/Flat-Earther/Evolutionary-Computation/tree/main/lab-04-candidate-moves"

METHODS = [
    ("candidate_k1", "Candidate moves (k = 1, nearest)", 1),
    ("candidate_k5", "Candidate moves (k = 5)", 5),
    ("candidate_k10", "Candidate moves (k = 10)", 10),
    ("candidate_k15", "Candidate moves (k = 15)", 15),
    ("candidate_k20", "Candidate moves (k = 20)", 20),
    ("candidate_k30", "Candidate moves (k = 30)", 30),
    ("candidate_k50", "Candidate moves (k = 50)", 50),
    ("steepest_2opt", "Full neighborhood (k = infinity)", 0),
]

RANKING_METHODS = [
    (f"{strategy}_k{candidate_count}", f"k = {candidate_count} - {label}", candidate_count)
    for candidate_count in (1, 5, 10, 15, 20, 30, 50)
    for strategy, label in (("distance_intra_costs_inter", "distance intra + costs inter"),
                            ("distance_plus_costs_all", "distance + costs intra/inter"))
]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def text(x: float, y: float, value: str, size: int = 20, fill: str = INK,
         weight: str = "400", family: str = "Arial", anchor: str = "start") -> str:
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}px" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{esc(value)}</text>')


def multiline(x: float, y: float, lines: list[str], size: int = 20, fill: str = INK,
             weight: str = "400", family: str = "Arial", line_height: int = 28) -> str:
    return "\n".join(text(x, y + index * line_height, line, size, fill, weight, family)
                     for index, line in enumerate(lines))


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
    return lines


def rect(x: float, y: float, width: float, height: float, fill: str = WHITE,
         stroke: str = "none", radius: float = 0, opacity: float = 1.0) -> str:
    return (f'<rect x="{x}" y="{y}" width="{width}" height="{height}" fill="{fill}" '
            f'stroke="{stroke}" rx="{radius}" opacity="{opacity}"/>')


def line(x1: float, y1: float, x2: float, y2: float, stroke: str = GRID, width: float = 1) -> str:
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}"/>'


def circle(cx: float, cy: float, radius: float, fill: str, opacity: float = 1.0) -> str:
    return f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{fill}" opacity="{opacity}"/>'


def crown_icon(parts: list[str], x: float, y: float, fill: str = "#e0a100", size: float = 42) -> None:
    scale = size / 42
    parts.append(
        f'<polygon points="{x},{y + 7 * scale} {x + 10 * scale},{y + 25 * scale} '
        f'{x + 21 * scale},{y + 5 * scale} {x + 32 * scale},{y + 25 * scale} '
        f'{x + 42 * scale},{y + 7 * scale} {x + 37 * scale},{y + 34 * scale} '
        f'{x + 5 * scale},{y + 34 * scale}" fill="{fill}" stroke="none"/>'
    )
    parts.append(rect(x + 6 * scale, y + 34 * scale, 30 * scale, 5 * scale, fill,
                      stroke="none", radius=1))


def warning_icon(parts: list[str], x: float, y: float, fill: str = "#d85d36", size: float = 42) -> None:
    scale = size / 42
    parts.append(
        f'<polygon points="{x + 21 * scale},{y} {x + 42 * scale},{y + 21 * scale} '
        f'{x + 21 * scale},{y + 42 * scale} {x},{y + 21 * scale}" '
        f'fill="{fill}" stroke="none"/>'
    )
    parts.append(text(x + 21 * scale, y + 30 * scale, "!", 26 * scale, WHITE, "700", anchor="middle"))


def page_start(title: str, kicker: str, number: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        rect(0, 0, WIDTH, HEIGHT, LIGHT, radius=0),
        rect(0, 0, WIDTH, 126, NAVY, radius=0),
        text(70, 42, kicker.upper(), 14, ORANGE, "700"),
        text(70, 93, title, 34, WHITE, "700"),
        text(WIDTH - 70, 46, "LAB 04", 15, "#b7d0e1", "700", anchor="end"),
        text(WIDTH - 70, 91, f"{number:02d}", 26, WHITE, "700", anchor="end"),
    ]


def page_end(parts: list[str], number: int) -> str:
    parts.extend([
        line(70, 1688, WIDTH - 70, 1688),
        text(70, 1722, "Evolutionary Computation - Candidate Moves", 14, MUTED),
        text(WIDTH - 70, 1722, f"{AUTHOR_ONE} - {AUTHOR_TWO}   |   {number:02d}", 14, MUTED, anchor="end"),
        "</svg>",
    ])
    return "\n".join(parts)


def cover_page(number: int) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        rect(0, 0, WIDTH, HEIGHT, LIGHT, radius=0),
        rect(0, 0, WIDTH, 650, NAVY, radius=0),
        circle(1080, 65, 210, BLUE, 0.36),
        circle(1120, 150, 125, TEAL, 0.42),
        circle(88, 625, 230, ORANGE, 0.92),
        text(76, 86, "EVOLUTIONARY COMPUTATION", 17, "#b7d0e1", "700"),
        text(76, 160, "LABORATORY 04", 22, ORANGE, "700"),
        text(76, 250, "Candidate", 62, WHITE, "700"),
        text(76, 326, "moves", 62, WHITE, "700"),
        text(80, 402, "for the Traveling Salesperson Problem with Node Costs", 20, "#d9e8f1"),
        rect(76, 470, 400, 70, "#ffffff", radius=35, opacity=0.12),
        text(112, 515, "ASSIGNMENT 4 - REPORT", 18, WHITE, "700"),
        rect(76, 570, 1088, 112, "#1b4669", "#477c9d", 18),
        text(112, 607, "SOURCE REPOSITORY", 14, ORANGE, "700"),
        text(112, 651, REPOSITORY_URL, 15, WHITE, "700"),
        text(76, 716, "Authors", 18, BLUE, "700"),
        text(76, 760, AUTHOR_ONE, 34, INK, "700"),
        text(76, 800, "160301", 20, MUTED),
        text(390, 760, AUTHOR_TWO, 34, INK, "700"),
        text(390, 800, "160292", 20, MUTED),
        rect(76, 890, 1088, 260, WHITE, GRID, 22),
        text(112, 950, "OBJECTIVE", 15, TEAL, "700"),
        text(112, 1012, "Accelerate steepest 2-opt local search", 30, INK, "700"),
        text(112, 1068, "Evaluate only moves introducing candidate edges.", 20, MUTED),
        text(112, 1102, "The supplied instances contain 200 nodes, so every solution selects 100.", 20, MUTED),
        rect(76, 1220, 520, 190, PALE_BLUE, radius=20),
        text(110, 1270, "INSTANCES", 14, BLUE, "700"),
        text(110, 1324, "TSPA and TSPB", 31, INK, "700"),
        text(110, 1370, "200 nodes each - 100 selected", 18, MUTED),
        rect(644, 1220, 520, 190, PALE_TEAL, radius=20),
        text(678, 1270, "EXPERIMENT", 14, TEAL, "700"),
        text(678, 1324, "k = 1, 5, 10, 15, 20, 30, 50", 24, INK, "700"),
        text(678, 1370, "plus full-neighborhood baseline", 18, MUTED),
        line(76, 1510, 1164, 1510, GRID, 1),
        text(76, 1565, "Pozna" + chr(0x144) + " University of Technology - Artificial Intelligence", 17, MUTED),
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
            "Lab 04 starts from random feasible cycles and compares full steepest search with a candidate-move version. "
            "The candidate version keeps only moves that introduce at least one candidate edge.", 97),
            19, MUTED, line_height=29),
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
    parts.append(text(x + 32, y + 43, title, 25, INK, "700"))
    parts.append(multiline(x + 32, y + 78, wrap(description, 125), 16, MUTED, line_height=23))
    code_y = y + 170
    code_height = height - 194
    parts.append(rect(x + 24, code_y, width - 48, code_height, NAVY, radius=12))
    for index, line_value in enumerate(code):
        indentation = len(line_value) - len(line_value.lstrip())
        parts.append(text(x + 44 + indentation * 10, code_y + 34 + index * 17,
                          line_value.lstrip(), 17, "#e2eef5", family="Consolas"))


def algorithms_page(number: int) -> str:
    parts = page_start("2. Candidate-move algorithm", "02 - algorithm", number)
    code = [
        "INPUT:",
        "  D[u][v]       rounded distance between vertices u and v",
        "  C[u]          cost of vertex u",
        "  n             number of vertices; k = ceil(n / 2)",
        "  K             candidate-list size (1, 5, 10, 15, 20, 30, or 50)",
        "  S0            random feasible cycle with k distinct vertices",
        "OUTPUT: locally optimal closed cycle S and objective F(S)",
        "",
        "OBJECTIVE AND INDEX FUNCTIONS:",
        "  F(S) = sum D[S[p]][S[next(p)]] + sum C[S[p]]",
        "  next(p) = (p + 1) mod k; previous(p) = (p - 1 + k) mod k",
        "  position[u] is the position of selected vertex u in S",
        "  all routes below omit the repeated closing vertex S[0]",
        "",
        "BUILD CANDIDATE EDGE SETS:",
        "  for u in range(0, n):",
        "    rank every v != u by D[u][v]                         # intra",
        "    for v in the first min(K, n - 1) ranked vertices:",
        "      insert undirected edge {u, v} into IntraCandidates",
        "    rank every v != u by D[u][v] + C[u] + C[v]          # inter",
        "    for v in the first min(K, n - 1) ranked vertices:",
        "      insert undirected edge {u, v} into InterCandidates",
        "  Candidate edges are stored in IntraCandidates and InterCandidates.",
        "",
        "DELTA FUNCTIONS (no neighboring route is reconstructed):",
        "  delta_2opt(S, i, j) = D[S[previous(i)]][S[j]]",
        "                       + D[S[i]][S[next(j)]]",
        "                       - D[S[previous(i)]][S[i]]",
        "                       - D[S[j]][S[next(j)]]",
        "  delta_replace(S, p, v) = D[S[previous(p)]][v] + D[v][S[next(p)]]",
        "                          + C[v] - D[S[previous(p)]][S[p]]",
        "                          - D[S[p]][S[next(p)]] - C[S[p]]",
        "",
        "CANDIDATE_NEIGHBORHOOD(S):",
        "  selected[u] <- false for every u; position[u] <- UNDEFINED for every u",
        "  for p in range(0, k):",
        "    selected[S[p]] <- true; position[S[p]] <- p",
        "  M <- empty list of moves; seen_2opt <- empty set",
        "  for first in range(0, k):",
        "    before <- S[previous(first)]",
        "    for v in IntraCandidates[before]:",
        "      if selected[v] == true:",
        "        second <- position[v]",
        "        if second > first + 1 and move is not wrap-around:",
        "          add 2-opt move (first, second) if not in seen_2opt",
        "    for v in IntraCandidates[S[first]]:",
        "      if selected[v] == true:",
        "        second <- previous(position[v])",
        "        if second > first + 1 and move is not wrap-around:",
        "          add 2-opt move (first, second) if not in seen_2opt",
        "  for p in range(0, k):",
        "    before <- S[previous(p)]; after <- S[next(p)]",
        "    for v in InterCandidates[before] UNION InterCandidates[after]:",
        "      if selected[v] == false:",
        "        add replacement move (p, v) to M",
        "  return M",
        "",
        "CANDIDATE_STEEPEST_SEARCH(S0):",
        "  S <- S0; current_cost <- F(S)",
        "  while True:",
        "    M <- CANDIDATE_NEIGHBORHOOD(S)",
        "    best_delta <- 0; best_move <- NONE",
        "    for each move m in M:                             # only candidates",
        "      delta <- delta_2opt(S,m) or delta_replace(S,m)",
        "      if delta < best_delta:",
        "        best_delta <- delta; best_move <- m",
        "    if best_move is NONE:",
        "      break",
        "    apply best_move to S; current_cost <- current_cost + best_delta",
        "  append S[0] to close the cycle and return S, current_cost",
    ]
    code_card(parts, 70, 160, 1100, 1440, "Candidate-move steepest local search",
              "The candidate method builds only eligible 2-opt and selected-to-unselected moves. The full-neighborhood baseline uses the same steepest loop but replaces CANDIDATE_NEIGHBORHOOD(S) with every valid move.",
              code, TEAL)
    return page_end(parts, number)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_data() -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    stats = {instance: read_csv(EVALUATION / f"{instance}_stats.csv") for instance in ("TSPA", "TSPB")}
    times = {instance: read_csv(EVALUATION / f"{instance}_times.csv") for instance in ("TSPA", "TSPB")}
    return stats, times


def read_ranking_data() -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    stats = {instance: read_csv(EVALUATION / f"{instance}_ranking_stats.csv") for instance in ("TSPA", "TSPB")}
    times = {instance: read_csv(EVALUATION / f"{instance}_ranking_times.csv") for instance in ("TSPA", "TSPB")}
    return stats, times


def fmt(value: str | float | int, places: int = 2) -> str:
    number = float(value)
    if places == 0:
        return str(int(round(number)))
    return f"{number:.{places}f}"


def table(parts: list[str], x: int, y: int, widths: list[int], headers: list[str], rows: list[list[str]],
          row_height: int = 44, font_size: int = 15,
          highlight_cells: dict[tuple[int, int], str] | None = None,
          bold_cells: set[tuple[int, int]] | None = None,
          symbols: dict[tuple[int, int], str] | None = None) -> int:
    total = sum(widths)
    highlight_cells = highlight_cells or {}
    bold_cells = bold_cells or set()
    symbols = symbols or {}
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
            if symbols.get(cell) == "crown":
                crown_icon(parts, cursor + width - 55, row_y + 9, size=22)
            elif symbols.get(cell) == "warning":
                warning_icon(parts, cursor + width - 55, row_y + 8, size=22)
            cursor += width
    parts.append(rect(x, y, total, row_height * (len(rows) + 1), "none", GRID, 8))
    return row_height * (len(rows) + 1)


def comparison_page(number: int, stats: dict[str, list[dict[str, str]]],
                    times: dict[str, list[dict[str, str]]]) -> str:
    parts = page_start("3. Algorithm comparison", "03 - comparison", number)
    labels = {method_id: label for method_id, label, _ in METHODS}
    score_by_instance = {
        instance: {row["method_name"]: row for row in stats[instance]}
        for instance in ("TSPA", "TSPB")
    }
    time_by_instance = {
        instance: {row["method_name"]: row for row in times[instance]}
        for instance in ("TSPA", "TSPB")
    }
    rows_scores = []
    rows_times = []
    for method_id, _, candidate_count in METHODS:
        rows_scores.append([
            labels[method_id],
            f"{fmt(score_by_instance['TSPA'][method_id]['avg'])}({fmt(score_by_instance['TSPA'][method_id]['min'], 0)} - {fmt(score_by_instance['TSPA'][method_id]['max'], 0)})",
            f"{fmt(score_by_instance['TSPB'][method_id]['avg'])}({fmt(score_by_instance['TSPB'][method_id]['min'], 0)} - {fmt(score_by_instance['TSPB'][method_id]['max'], 0)})",
        ])
        rows_times.append([
            labels[method_id],
            f"{fmt(time_by_instance['TSPA'][method_id]['average_ms'])}({fmt(time_by_instance['TSPA'][method_id]['minimum_ms'])} - {fmt(time_by_instance['TSPA'][method_id]['maximum_ms'])}) ms",
            f"{fmt(time_by_instance['TSPB'][method_id]['average_ms'])}({fmt(time_by_instance['TSPB'][method_id]['minimum_ms'])} - {fmt(time_by_instance['TSPB'][method_id]['maximum_ms'])}) ms",
        ])

    tspa_score_best = min(range(len(METHODS)), key=lambda index: float(rows_scores[index][1].split("(")[0]))
    tspb_score_best = min(range(len(METHODS)), key=lambda index: float(rows_scores[index][2].split("(")[0]))
    tspa_min_best = min(range(len(METHODS)), key=lambda index: float(score_by_instance["TSPA"][METHODS[index][0]]["min"]))
    tspb_min_best = min(range(len(METHODS)), key=lambda index: float(score_by_instance["TSPB"][METHODS[index][0]]["min"]))
    tspa_max_worst = max(range(len(METHODS)), key=lambda index: float(score_by_instance["TSPA"][METHODS[index][0]]["max"]))
    tspb_max_worst = max(range(len(METHODS)), key=lambda index: float(score_by_instance["TSPB"][METHODS[index][0]]["max"]))
    tspa_time_best = min(range(len(METHODS)), key=lambda index: float(rows_times[index][1].split("(")[0]))
    tspb_time_best = min(range(len(METHODS)), key=lambda index: float(rows_times[index][2].split("(")[0]))
    tspa_time_min = min(range(len(METHODS)), key=lambda index: float(time_by_instance["TSPA"][METHODS[index][0]]["minimum_ms"]))
    tspb_time_min = min(range(len(METHODS)), key=lambda index: float(time_by_instance["TSPB"][METHODS[index][0]]["minimum_ms"]))
    tspa_time_max = max(range(len(METHODS)), key=lambda index: float(time_by_instance["TSPA"][METHODS[index][0]]["maximum_ms"]))
    tspb_time_max = max(range(len(METHODS)), key=lambda index: float(time_by_instance["TSPB"][METHODS[index][0]]["maximum_ms"]))

    text_y = 175
    parts.extend([
        text(70, text_y, "Objective score: average (minimum - maximum); lower values are better.", 20, INK, "700"),
    ])
    table(parts, 70, 205, [380, 360, 360], ["Algorithm", "TSPA", "TSPB"], rows_scores,
          row_height=40, font_size=14,
          highlight_cells={(tspa_score_best, 1): BEST_SCORE, (tspb_score_best, 2): BEST_SCORE},
          bold_cells={(tspa_score_best, 1), (tspb_score_best, 2)},
          symbols={(tspa_min_best, 1): "crown", (tspb_min_best, 2): "crown",
                   (tspa_max_worst, 1): "warning", (tspb_max_worst, 2): "warning"})

    parts.append(text(70, 600, "Runtime: average (minimum - maximum) milliseconds; lower values are better.", 20, INK, "700"))
    table(parts, 70, 630, [380, 360, 360], ["Algorithm", "TSPA", "TSPB"], rows_times,
          row_height=40, font_size=13,
          highlight_cells={(tspa_time_best, 1): BEST_TIME, (tspb_time_best, 2): BEST_TIME},
          bold_cells={(tspa_time_best, 1), (tspb_time_best, 2)},
          symbols={(tspa_time_min, 1): "crown", (tspb_time_min, 2): "crown",
                   (tspa_time_max, 1): "warning", (tspb_time_max, 2): "warning"})

    best_score_tspa = METHODS[tspa_score_best][0]
    best_score_tspb = METHODS[tspb_score_best][0]
    best_time_tspa = METHODS[tspa_time_best][0]
    best_time_tspb = METHODS[tspb_time_best][0]
    parts.extend([
        rect(70, 1035, 18, 18, BEST_SCORE, radius=4),
        text(98, 1050, "lowest average objective", 15, MUTED),
        rect(330, 1035, 18, 18, BEST_TIME, radius=4),
        text(358, 1050, "lowest average runtime", 15, MUTED),
        text(630, 1050, "lowest minimum score/time", 15, MUTED),
        text(880, 1050, "highest maximum score/time", 15, MUTED),
    ])
    crown_icon(parts, 600, 1031, size=22)
    warning_icon(parts, 850, 1029, size=22)
    parts.extend([
        rect(70, 1090, 1100, 270, PALE_TEAL, radius=20),
        text(108, 1138, "Best results in the comparison", 24, INK, "700"),
        multiline(108, 1190, [
            f"TSPA score: {labels[best_score_tspa]} ({fmt(score_by_instance['TSPA'][best_score_tspa]['avg'])}).",
            f"TSPB score: {labels[best_score_tspb]} ({fmt(score_by_instance['TSPB'][best_score_tspb]['avg'])}).",
            f"TSPA time: {labels[best_time_tspa]} ({fmt(time_by_instance['TSPA'][best_time_tspa]['average_ms'])} ms).",
            f"TSPB time: {labels[best_time_tspb]} ({fmt(time_by_instance['TSPB'][best_time_tspb]['average_ms'])} ms).",
        ], 17, MUTED, line_height=34),
    ])
    return page_end(parts, number)


def additional_experiment_page(number: int,
                               stats: dict[str, list[dict[str, str]]],
                               times: dict[str, list[dict[str, str]]]) -> str:
    parts = page_start("7. Additional experiment", "07 - additional experiment", number)
    score_by_instance = {
        instance: {row["method_name"]: row for row in stats[instance]}
        for instance in ("TSPA", "TSPB")
    }
    time_by_instance = {
        instance: {row["method_name"]: row for row in times[instance]}
        for instance in ("TSPA", "TSPB")
    }
    rows_scores = []
    rows_times = []
    for method_id, label, _ in RANKING_METHODS:
        rows_scores.append([
            label,
            f"{fmt(score_by_instance['TSPA'][method_id]['avg'])}({fmt(score_by_instance['TSPA'][method_id]['min'], 0)} - {fmt(score_by_instance['TSPA'][method_id]['max'], 0)})",
            f"{fmt(score_by_instance['TSPB'][method_id]['avg'])}({fmt(score_by_instance['TSPB'][method_id]['min'], 0)} - {fmt(score_by_instance['TSPB'][method_id]['max'], 0)})",
        ])
        rows_times.append([
            label,
            f"{fmt(time_by_instance['TSPA'][method_id]['average_ms'])}({fmt(time_by_instance['TSPA'][method_id]['minimum_ms'])} - {fmt(time_by_instance['TSPA'][method_id]['maximum_ms'])}) ms",
            f"{fmt(time_by_instance['TSPB'][method_id]['average_ms'])}({fmt(time_by_instance['TSPB'][method_id]['minimum_ms'])} - {fmt(time_by_instance['TSPB'][method_id]['maximum_ms'])}) ms",
        ])

    tspa_score_best = min(range(len(RANKING_METHODS)), key=lambda index: float(rows_scores[index][1].split("(")[0]))
    tspb_score_best = min(range(len(RANKING_METHODS)), key=lambda index: float(rows_scores[index][2].split("(")[0]))
    tspa_time_best = min(range(len(RANKING_METHODS)), key=lambda index: float(rows_times[index][1].split("(")[0]))
    tspb_time_best = min(range(len(RANKING_METHODS)), key=lambda index: float(rows_times[index][2].split("(")[0]))

    parts.append(text(70, 175, "Objective score: average (minimum - maximum); lower values are better.", 20, INK, "700"))
    table(parts, 70, 200, [380, 360, 360], ["Ranking policy", "TSPA", "TSPB"], rows_scores,
          row_height=28, font_size=11,
          highlight_cells={(tspa_score_best, 1): BEST_SCORE, (tspb_score_best, 2): BEST_SCORE},
          bold_cells={(tspa_score_best, 1), (tspb_score_best, 2)})

    parts.append(text(70, 650, "Runtime: average (minimum - maximum) milliseconds; lower values are better.", 20, INK, "700"))
    table(parts, 70, 675, [380, 360, 360], ["Ranking policy", "TSPA", "TSPB"], rows_times,
          row_height=28, font_size=10,
          highlight_cells={(tspa_time_best, 1): BEST_TIME, (tspb_time_best, 2): BEST_TIME},
          bold_cells={(tspa_time_best, 1), (tspb_time_best, 2)})

    best_score_tspa = RANKING_METHODS[tspa_score_best][1]
    best_score_tspb = RANKING_METHODS[tspb_score_best][1]
    best_time_tspa = RANKING_METHODS[tspa_time_best][1]
    best_time_tspb = RANKING_METHODS[tspb_time_best][1]
    parts.extend([
        rect(70, 1140, 18, 18, BEST_SCORE, radius=4),
        text(98, 1155, "lowest average objective", 15, MUTED),
        rect(330, 1140, 18, 18, BEST_TIME, radius=4),
        text(358, 1155, "lowest average runtime", 15, MUTED),
        rect(70, 1190, 1100, 315, PALE_TEAL, radius=20),
        text(108, 1238, "Ranking-policy comparison", 24, INK, "700"),
        multiline(108, 1290, [
            f"TSPA best objective: {best_score_tspa} ({fmt(score_by_instance['TSPA'][RANKING_METHODS[tspa_score_best][0]]['avg'])}).",
            f"TSPB best objective: {best_score_tspb} ({fmt(score_by_instance['TSPB'][RANKING_METHODS[tspb_score_best][0]]['avg'])}).",
            f"TSPA fastest average: {best_time_tspa} ({fmt(time_by_instance['TSPA'][RANKING_METHODS[tspa_time_best][0]]['average_ms'])} ms).",
            f"TSPB fastest average: {best_time_tspb} ({fmt(time_by_instance['TSPB'][RANKING_METHODS[tspb_time_best][0]]['average_ms'])} ms).",
        ], 17, MUTED, line_height=34),
    ])
    return page_end(parts, number)


def route_lines(route: list[int], max_chars: int = 40) -> list[str]:
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


def read_route(instance: str, method_id: str, worst: bool = False) -> list[int]:
    suffix = "_worst" if worst else ""
    path = EVALUATION / "results" / f"{instance}_{method_id}{suffix}.csv"
    return [int(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def plot_path(instance: str, method_id: str, worst: bool = False) -> Path:
    suffix = "_worst" if worst else ""
    return EVALUATION / "plots" / f"{instance}_{method_id}{suffix}.svg"


def visual_page(number: int, instance: str, subset: list[tuple[str, str, int]],
                stats: dict[str, list[dict[str, str]]],
                times: dict[str, list[dict[str, str]]], worst: bool = False) -> str:
    mode = "Worst" if worst else "Best"
    section = "5 - worst solutions" if worst else "4 - best solutions"
    parts = page_start(f"{section.split(' - ')[0]}. {mode} solutions - {instance}", section, number)
    parts.append(text(70, 160, "The plots show node cost using colour and size. The line represents the closed cycle.", 17, MUTED))
    stats_by_id = {row["method_name"]: row for row in stats[instance]}
    times_by_id = {row["method_name"]: row for row in times[instance]}
    labels = {method_id: label for method_id, label, _ in METHODS}
    best_method_id = min(stats[instance], key=lambda row: float(row["min"]))["method_name"]
    worst_method_id = max(stats[instance], key=lambda row: float(row["max"]))["method_name"]
    for index, (method_id, _, _) in enumerate(subset):
        y = 195 + index * 365
        row = stats_by_id[method_id]
        visual_label = labels[method_id].replace(", nearest", "")
        parts.append(rect(70, y, 1100, 335, WHITE, GRID, 18))
        parts.append(text(98, y + 30, visual_label, 17 if len(visual_label) < 33 else 15, INK, "700"))
        parts.append(text(98, y + 56, f"min={fmt(row['min'], 0)}  max={fmt(row['max'], 0)}  avg={fmt(row['avg'])}", 13, MUTED))
        objective = row["max"] if worst else row["min"]
        parts.append(rect(125, y + 93, 185, 34, PALE_ORANGE if worst else PALE_TEAL, radius=17))
        parts.append(text(217.5, y + 116, f"{mode.lower()} = {fmt(objective, 0)}", 13, INK, "700", anchor="middle"))
        runtime = times_by_id[method_id]
        parts.append(rect(125, y + 176, 185, 92, PALE_BLUE, "#b9d6e8", 14))
        parts.append(text(217.5, y + 199, "TIME (ms)", 11, BLUE, "700", anchor="middle"))
        parts.append(text(217.5, y + 224, f"avg = {fmt(runtime['average_ms'])}", 12, INK, "700", anchor="middle"))
        parts.append(text(217.5, y + 246,
                          f"min = {fmt(runtime['minimum_ms'])}   max = {fmt(runtime['maximum_ms'])}",
                          10, MUTED, anchor="middle"))
        image(parts, plot_path(instance, method_id, worst), 365, y + 4, 320, 320)
        parts.append(text(710, y + 48, f"{mode} solution nodes:", 16, BLUE, "700"))
        parts.append(multiline(710, y + 82, route_lines(read_route(instance, method_id, worst), 50), 13, MUTED,
                               family="Consolas", line_height=16))
        if not worst and method_id == best_method_id:
            crown_icon(parts, 1110, y + 270)
        if worst and method_id == worst_method_id:
            warning_icon(parts, 1110, y + 265)
    return page_end(parts, number)


def conclusions_page(number: int, stats: dict[str, list[dict[str, str]]],
                    times: dict[str, list[dict[str, str]]]) -> str:
    labels = {method_id: label for method_id, label, _ in METHODS}
    best = {}
    best_individual = {}
    fastest = {}
    slowest = {}
    for instance in ("TSPA", "TSPB"):
        best[instance] = min(stats[instance], key=lambda row: float(row["avg"]))
        best_individual[instance] = min(stats[instance], key=lambda row: float(row["min"]))
        fastest[instance] = min(times[instance], key=lambda row: float(row["average_ms"]))
        slowest[instance] = max(times[instance], key=lambda row: float(row["average_ms"]))
    k1 = {instance: next(row for row in stats[instance] if row["method_name"] == "candidate_k1")
          for instance in ("TSPA", "TSPB")}
    k50 = {instance: next(row for row in stats[instance] if row["method_name"] == "candidate_k50")
           for instance in ("TSPA", "TSPB")}
    runtime_conclusion = (
        f"Runtime followed the expected pruning trade-off: candidate moves with k = 1 were fastest in both "
        f"TSPA and TSPB, while the full-neighborhood baseline was the slowest. Increasing K made the "
        f"candidate neighborhood larger and generally increased the average runtime."
    )
    quality_conclusion = (
        f"The solution-quality trend went in the opposite direction. The single-nearest case had averages "
        f"{fmt(k1['TSPA']['avg'])} (TSPA) and {fmt(k1['TSPB']['avg'])} (TSPB). Increasing K improved the "
        f"averages strongly up to k = 20, which was the best average setting for both instances; k = 30 and "
        f"k = 50 then stayed close to the full-neighborhood quality, showing a plateau rather than unlimited "
        f"improvement."
    )
    individual_conclusion = (
        f"The best individual routes did not have to come from k = infinity: TSPA's lowest observed value "
        f"came from {labels[best_individual['TSPA']['method_name']]} ({fmt(best_individual['TSPA']['min'], 0)}), "
        f"and TSPB's came from {labels[best_individual['TSPB']['method_name']]} "
        f"({fmt(best_individual['TSPB']['min'], 0)}). A plausible explanation is that restricting the "
        f"neighborhood changes the sequence of accepted moves and therefore the local optimum basin; one "
        f"candidate-restricted run can avoid a full-neighborhood move sequence that ends in a worse local optimum."
    )
    parts = page_start("6. Conclusions", "06 - conclusions", number)
    parts.extend([
        multiline(70, 190, wrap("Candidate moves substantially reduce the time needed by steepest local search because the algorithm evaluates only a small directly generated subset of the full neighborhood.", 92), 20, MUTED, line_height=29),
        multiline(70, 248, wrap("Increasing the candidate-list size generally improves solution quality, but also increases the number of moves evaluated and therefore the runtime.", 92), 20, MUTED, line_height=29),
        rect(70, 330, 1100, 900, WHITE, GRID, 20),
        text(108, 390, "Main conclusions", 25, INK, "700"),
        multiline(108, 450, wrap(f"For TSPA, the lowest average objective was obtained by {labels[best['TSPA']['method_name']]} ({fmt(best['TSPA']['avg'])}). For TSPB, the best average was obtained by {labels[best['TSPB']['method_name']]} ({fmt(best['TSPB']['avg'])}).", 92), 19, MUTED, line_height=29),
        multiline(108, 580, wrap(runtime_conclusion, 92), 19, MUTED, line_height=29),
        multiline(108, 745, wrap(quality_conclusion, 92), 19, MUTED, line_height=29),
        multiline(108, 910, wrap(individual_conclusion, 92), 19, MUTED, line_height=29),
        multiline(108, 1075, wrap("All generated routes passed structural validation, and every final objective agreed with the accumulated direct move deltas.", 92), 19, MUTED, line_height=29),
        rect(70, 1305, 1100, 130, PALE_BLUE, "#b9d6e8", 20),
        text(108, 1350, "SOURCE REPOSITORY", 15, BLUE, "700"),
        text(108, 1400, REPOSITORY_URL, 16, INK, "700"),
    ])
    return page_end(parts, number)


def dark_divider_page(number: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}"><rect width="{WIDTH}" height="{HEIGHT}" fill="{NAVY}"/></svg>')


def large_visual_page(number: int, instance: str, subset: list[tuple[str, str, int]],
                      stats: dict[str, list[dict[str, str]]], worst: bool = False) -> str:
    mode = "Worst" if worst else "Best"
    accent = ORANGE if worst else TEAL
    background = "#ffe8d8" if worst else "#def2ec"
    border = "#e4a06f" if worst else "#8ac5b6"
    labels = {method_id: label for method_id, label, _ in METHODS}
    stats_by_id = {row["method_name"]: row for row in stats[instance]}
    parts = page_start(f"8. Large {mode.lower()} visualizations - {instance}",
                       f"appendix - {mode.lower()} solutions", number)
    for y, (method_id, _, _) in zip([155, 915], subset):
        row = stats_by_id[method_id]
        route = read_route(instance, method_id, worst)
        objective = row["max"] if worst else row["min"]
        parts.append(rect(70, y, 1100, 740, background, border, 22))
        parts.append(rect(810, y + 24, 224, 40, accent, radius=20))
        parts.append(text(922, y + 50, f"{mode.upper()} SOLUTION", 14, WHITE, "700", anchor="middle"))
        parts.append(text(810, y + 98, labels[method_id], 17 if len(labels[method_id]) > 29 else 20, INK, "700"))
        parts.append(multiline(810, y + 126, [f"min={fmt(row['min'], 0)}", f"max={fmt(row['max'], 0)}", f"avg={fmt(row['avg'])}"],
                               12, MUTED, line_height=18))
        parts.append(rect(810, y + 188, 210, 40, WHITE, border, 12))
        parts.append(text(915, y + 215, f"objective {fmt(objective, 0)}", 14, INK, "700", anchor="middle"))
        image(parts, plot_path(instance, method_id, worst), 85, y + 25, 700, 700)
        parts.append(text(810, y + 270, f"{mode} solution nodes:", 16, accent, "700"))
        parts.append(multiline(810, y + 306, route_lines(route, 25), 12, INK, family="Consolas", line_height=18))
        parts.append(text(810, y + 690, f"{len(set(route[:-1]))} selected nodes; closed route", 14, accent, "700"))
    return page_end(parts, number)


def main() -> None:
    stats, times = read_data()
    ranking_stats, ranking_times = read_ranking_data()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir()
    subsets = [METHODS[index:index + 4] for index in range(0, len(METHODS), 4)]
    pair_subsets = [METHODS[index:index + 2] for index in range(0, len(METHODS), 2)]
    pages = [
        cover_page(1),
        problem_page(2),
        algorithms_page(3),
        comparison_page(4, stats, times),
    ]
    for instance in ("TSPA", "TSPB"):
        for subset in subsets:
            pages.append(visual_page(len(pages) + 1, instance, subset, stats, times))
    for instance in ("TSPA", "TSPB"):
        for subset in subsets:
            pages.append(visual_page(len(pages) + 1, instance, subset, stats, times, True))
    pages.append(conclusions_page(len(pages) + 1, stats, times))
    pages.append(additional_experiment_page(len(pages) + 1, ranking_stats, ranking_times))
    pages.append(dark_divider_page(len(pages) + 1))
    for instance in ("TSPA", "TSPB"):
        for subset in pair_subsets:
            pages.append(large_visual_page(len(pages) + 1, instance, subset, stats))
    for instance in ("TSPA", "TSPB"):
        for subset in pair_subsets:
            pages.append(large_visual_page(len(pages) + 1, instance, subset, stats, True))
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
