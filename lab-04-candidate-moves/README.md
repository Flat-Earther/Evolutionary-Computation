# Lab 04 - Candidate Moves

This laboratory accelerates the steepest local search from Lab 03 by evaluating only candidate moves. The selected neighborhood is the 2-opt intra-route neighborhood together with selected-to-unselected node exchange.

## Methods and parameter experiment

The experiment evaluates the full-neighborhood baseline and a candidate-move method for several candidate-list sizes. By default it tests `k = 1, 5, 10, 15, 20, 30, 50`. The `k = 1` case uses only the single nearest candidate edge from each endpoint. All methods use the same 200 pre-generated random starting cycles for a given instance:

1. **Steepest local search - full neighborhood**
   - evaluates every valid 2-opt move, i.e. every reversal of a route segment of at least two nodes except the reversal of the whole route (reversing two neighboring nodes swaps them);
   - evaluates every selected-to-unselected replacement;
   - applies the improving move with the most negative objective delta.
2. **Steepest local search - candidate moves (`k`)**
   - uses the same steepest rule;
   - evaluates only moves that introduce at least one candidate edge;
   - is run separately for every tested candidate-list size;
   - the `k = 1` variant is reported as the single-nearest-candidate case.

For intra-route moves, the `k` nearest vertices are ranked by edge length. For inter-route moves, they are ranked by edge length plus the costs of the two vertices. Candidate edges are stored symmetrically, so an edge selected by either endpoint is available to the candidate-move generator.

Candidate moves are generated directly from the candidate lists. The candidate method does not enumerate the full neighborhood and then filter it. A 2-opt move is accepted into the candidate neighborhood when at least one of its two new boundary edges is a candidate edge. A node replacement is accepted when at least one of its two new incident edges is a candidate edge.

All move evaluations use direct objective deltas. The implementation does not rebuild neighboring routes or recompute the complete objective for every move. After each run, the final objective is recomputed and checked against the accumulated deltas.

## Implementation and performance

The local search is implemented for speed without changing what it computes: every iteration applies the move with the lowest delta, and ties are broken by a fixed move order, the scan order of a straightforward implementation that materialises every neighbourhood as a list of moves. Every run therefore ends in exactly the same local optimum as that straightforward implementation, only faster.

The first version of this lab left out 2-opt moves that reverse exactly two neighbouring nodes (only segments of three or more nodes were reversed, apart from a few wrap-around cases). Such a move is a proper 2-opt move — it removes two non-adjacent edges — so both neighbourhoods now include it. This changes the results: with the same starting solutions, 80–96% of the runs (depending on the method) end in a better local optimum, and the average objective drops by 0.7% (`k = 1`) to 2.0%, about 1.5% for the full neighbourhood.

* **No allocation in the search loop.** Moves are evaluated on the fly; the distance matrix is one contiguous array; the route is stored with sentinel copies of its ends, so neighbours are read without modulo arithmetic; route-edge lengths and node positions are cached and updated incrementally after each move.
* **Full neighbourhood.** Each row of 2-opt moves and each position's exchange scan is reduced to its minimum without branches (the exchange scan runs over all nodes with a penalty for selected ones, which the compiler vectorises); the arg-min is located only when a row beats the best move so far.
* **Candidate moves.** Candidate lists are stored in compressed form with precomputed delta parts. A per-list bitmask, updated through mirror entries when a node enters or leaves the solution, lets 2-opt scans visit only selected candidates and exchange scans only unselected ones. Every selected node is visited once: its 2-opt list yields both moves that introduce a candidate edge, and each pair of selected nodes is evaluated once, from the endpoint with the smaller position. Exchange lists are sorted by `d(u, v) + cost(v)`, so a scan stops at the first candidate that can no longer match the best move (exact, because distances are non-negative). Tie-breaking uses each move's rank in the original scan order, so the visiting order is free.

Equivalence with the straightforward implementation (with the same neighbourhood) was verified run by run (identical final routes and objectives) on TSPA/TSPB for the full neighbourhood and every tested candidate-list size and ranking policy, and on many random instances including tiny and odd-sized ones.

## Evaluation and timing

Each method and each candidate-list size is run 200 times for TSPA and TSPB. The same random starting cycles are used for all methods of a given instance. The runs of all methods are interleaved (for each starting cycle, every method once), so that changes of the processor clock during the experiment affect all methods alike. Only the local search itself is timed; building the candidate lists is measured separately (median of 25 constructions) because the lists depend only on the instance, the list size and the definition of "nearest". The evaluation stores:

* objective minimum, maximum, average, and standard deviation;
* best and worst closed routes;
* best and worst SVG visualizations;
* per-run runtime average, minimum, and maximum in milliseconds, and the candidate-list construction time.

The runtime CSV files use the following format (`candidate_list_ms` is 0 for the full neighbourhood):

```text
method_name,candidate_count,average_ms,minimum_ms,maximum_ms,candidate_list_ms
```

## Additional experiment: definitions of "nearest"

Candidate edges of 2-opt moves (intra) and of exchanges (inter) are chosen independently, each by one of three rankings of the other vertices `v` of a vertex `u`:

1. **distance** - `d(u, v)`;
2. **cost** - `c(v)`;
3. **distance + cost** - `d(u, v) + c(v)`.

(The cost of `u` itself would add the same amount to every score, so it does not change the ranking.) All 3 x 3 combinations are evaluated for `k = 1, 5, 10, 15, 20, 30, 50`, together with the full neighbourhood, in one interleaved session per instance; the definition proposed in the assignment (distance for intra, distance + cost for inter) is the one used by the main experiment. The results are written to `{TSPA,TSPB}_ranking_stats.csv` (`intra,inter,candidate_count,min,max,avg,sd`), `{TSPA,TSPB}_ranking_times.csv` (`intra,inter,candidate_count,average_ms,minimum_ms,maximum_ms,candidate_list_ms`) and `{TSPA,TSPB}_ranking_best.csv` (best route of every configuration); the full neighbourhood appears as `none,none,0`.

Run this experiment with:

```text
build/lab04.exe --ranking-experiment --seed 20260404
```

## Build and run

From this directory:

```text
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
build/lab04.exe --seed 20260404
```

Running times are part of the results, so the build must be optimised. `CMakeLists.txt` defaults to `Release` (`-O3`) when no build type is given; building without optimisation makes the search more than ten times slower. For GCC/Clang the instruction-set level is set by `LAB04_ARCH` (default `x86-64-v2`, supported by practically every x86-64 CPU of the last decade). On a CPU with AVX2, `-DLAB04_ARCH=x86-64-v3` makes the full-neighbourhood baseline somewhat faster; `-DLAB04_ARCH=` keeps the compiler default.

The executable accepts `TSPA` or `TSPB` to run one instance, `--data-dir DIR` to override the data location, and `--candidate-counts K1,K2,...` to select the candidate-list sizes. For example:

```text
build/lab04.exe --candidate-counts 1,5,10,15,20,30,50 --seed 20260404
```

The singular `--candidate-count K` option remains available for running one candidate-list size.

Evaluation artifacts are written to:

```text
lab-04-candidate-moves/evaluation/
```

The report is generated from the evaluation files with:

```text
python generate_report.py
```

It builds the report as HTML (`.report-build/report.html`) and prints it to `report.pdf` with a headless Chromium-based browser - Microsoft Edge or Google Chrome, or the one named by the `REPORT_BROWSER` environment variable; `--html-only` skips the PDF. It also checks every reported best solution with the data and formulas of `problem-description/data/Solution checker.xlsx`. The generated report is available at:

```text
lab-04-candidate-moves/report.pdf
```
