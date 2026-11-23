# Lab 05 - Move Evaluations from Previous Iterations

This laboratory makes the steepest local search faster by reusing move evaluations (deltas) from previous iterations. The neighbourhood is the best one of Lab 03: 2-opt as the intra-route move and the exchange of a selected and an unselected node as the inter-route move. Improving moves of both kinds are kept in one list of moves (LM), ordered by delta, and a move taken from LM is applied without being evaluated again. Starting solutions are random.

## Methods

All methods are run from the same 200 random starting cycles per instance (the same generator and seed as in Lab 04):

1. **Steepest local search - full neighbourhood (baseline)** - evaluates every 2-opt move and every exchange in every iteration (the Lab 04 implementation, without the mechanisms below).
2. **LM - new moves evaluated after each move** - the list of improving moves from the lecture. All moves of the starting solution are evaluated once; after a move is applied, only the new moves are evaluated (2-opt moves that remove one of the two new edges, exchanges of the nodes whose neighbours changed, and exchanges that insert the node that has just been removed) and the improving ones are added to LM.
3. **LM - alternative algorithm** - the algorithm advised in the assignment: no moves are evaluated after a move is applied; when LM contains no applicable move, LM is cleared and all moves are evaluated again. The search stops when such a fresh evaluation gives no applicable move.
4. **Candidate moves, k = 10 (Lab 04)** - for reference only; LM is not combined with candidate moves.

## The list of moves

A stored move keeps only node indices: a 2-opt move the two edges it removes, with the directions they had when it was evaluated (`a -> b`, `c -> d`, adding `(a, c)` and `(b, d)`); an exchange the removed node, its two neighbours and the inserted node. The delta depends only on these nodes, so it stays valid as long as the move can be applied. When LM is browsed from the best delta, a stored 2-opt move is:

1. **removed** from LM if one of its edges no longer exists;
2. **kept** in LM (and skipped) if both edges exist but in a different relative direction - it may become applicable later;
3. **applied** and removed from LM if both edges exist in the same relative direction (also both reversed).

An exchange is applied if the removed node still lies between the same two neighbours (in either order) and the inserted node is still not selected; otherwise it is removed.

Every pair of edges is evaluated in both reconnections: the one applicable now and the one with relatively inverted edges, which becomes applicable after another move reverses one of the edges. This includes the evaluation of the starting solution. In the experiment 31-32% of the 2-opt moves applied by LM had been evaluated with relatively inverted edges.

Among the applicable moves with the best delta, the one that comes first in the scan order of the baseline is applied. The LM search with new moves therefore applies the same moves as the baseline and reaches the same local optimum from every starting solution (verified for all 200 runs on both instances).

## Implementation and performance

* **LM as a bucket queue.** Deltas are integers between `-(2 * max distance + max cost)` and `-1`, so LM is an array of buckets indexed by `-delta`, each a linked list of moves, with a bit mask of the non-empty buckets. Insertion takes constant time; browsing visits the moves in the order of delta without sorting. A stored move takes 16 bytes; its delta is given by its bucket.
* **Checks in constant time.** The successor of every node is stored (`-1` for unselected nodes), so `x -> y` is an edge exactly when `succ(x) == y`. Both move types are checked without branching on the type, which is unpredictable while browsing.
* **Evaluation.** The route has sentinel copies of its ends and cached edge lengths. Scans write every move into a buffer and keep only the improving ones without branches; exchange scans run over whole rows of the distance matrix four nodes at a time (SSE2), with a prohibitive insertion cost for selected nodes.
* **Memory.** The pool of moves and the buckets are allocated once per instance and reused by all runs; within a run the pool is append-only.
* **Verification.** After every run the objective is recomputed and compared with the accumulated deltas. The experiment also checks that the result of every LM run is a local optimum of the full neighbourhood and counts the runs that end in exactly the baseline's local optimum.

With these measures a run of the LM search with new moves takes about 0.35 ms on TSPA and TSPB, against about 0.82 ms for the (vectorised) full-neighbourhood baseline - 2.3-2.4x faster, although it computes 16x fewer deltas. Most of the remaining time goes to inserting improving moves and checking them later: a random starting solution has about 9,800 improving moves (half of all moves), and about 99% of all moves inserted into LM are later removed because an edge or node is gone.

## Evaluation

Each method is run 200 times on TSPA and TSPB. The runs of all methods are interleaved (for each starting cycle, every method once), so that changes of the processor clock affect all methods alike. Only the local search itself is timed. The evaluation stores:

* `{TSPA,TSPB}_stats.csv` - `method_name,min,max,avg,sd` of the objective;
* `{TSPA,TSPB}_times.csv` - `method_name,average_ms,minimum_ms,maximum_ms` per run;
* `{TSPA,TSPB}_work.csv` - per-run averages of the work counters:

  ```text
  method_name,applied,applied_two_opt,applied_inverted,evaluated,inserted,initial_inserted,checked,removed,not_applicable,full_evaluations,same_as_baseline
  ```

  `evaluated` is the number of deltas computed (for the baseline: (applied moves + 1) x 14,949 moves of the full neighbourhood), `inserted`/`initial_inserted` the moves added to LM in total and by the evaluation of the starting solution, `checked` the stored moves checked while browsing LM, of which `removed` were removed (situation 1) and `not_applicable` kept (situation 2), and `same_as_baseline` the number of runs ending in exactly the baseline's local optimum. Counters that do not apply to a method are empty;
* `results/` - best and worst closed routes of every method;
* `plots/` - SVG visualisations of the best and worst routes.

## Build and run

From this directory:

```text
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
build/lab05.exe --seed 20260404
```

Running times are part of the results, so the build must be optimised; `CMakeLists.txt` defaults to `Release` (`-O3`). For GCC/Clang the instruction-set level is set by `LAB05_ARCH` (default `x86-64-v2`); `-DLAB05_ARCH=` keeps the compiler default. The executable accepts `TSPA` or `TSPB` to run one instance, `--data-dir DIR` to override the data location and `--seed N` for the starting solutions.

Evaluation artifacts are written to:

```text
lab-05-previous-deltas/evaluation/
```

The report is generated from the evaluation files with:

```text
python generate_report.py
```

It builds the report as HTML (`.report-build/report.html`) and prints it to `report.pdf` with a headless Chromium-based browser - Microsoft Edge or Google Chrome, or the one named by the `REPORT_BROWSER` environment variable; `--html-only` skips the PDF. It also checks every reported best solution with the data and formulas of `problem-description/data/Solution checker.xlsx`. The generated report is available at:

```text
lab-05-previous-deltas/report.pdf
```
