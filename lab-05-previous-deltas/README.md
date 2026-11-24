# Lab 05 - Move Evaluations from Previous Iterations

This laboratory makes the steepest local search faster by reusing move evaluations (deltas) from previous iterations. The neighbourhood is the best one of Lab 03: 2-opt as the intra-route move and the exchange of a selected and an unselected node as the inter-route move. Improving moves of both kinds are kept in one list of moves (LM), ordered by delta, and a move taken from LM is applied without being evaluated again. Starting solutions are random.

## Methods

All methods are run from the same 200 random starting cycles per instance (the same generator and seed as in Lab 04):

1. **Steepest local search - full neighbourhood (baseline)** - evaluates every 2-opt move and every exchange in every iteration (the Lab 04 implementation, without the mechanisms below).
2. **LM - new moves evaluated after each move** - the list of improving moves from the lecture. All moves of the starting solution are evaluated once; after a move is applied, only the new moves are evaluated (2-opt moves that remove one of the two new edges, exchanges of the nodes whose neighbours changed, and exchanges that insert the node that has just been removed) and the improving ones are added to LM.
3. **LM - alternative algorithm** - the algorithm advised in the assignment: no moves are evaluated after a move is applied; when LM contains no applicable move, LM is cleared and all moves are evaluated again. The search stops when such a fresh evaluation gives no applicable move.
4. **Candidate moves, k = 10 (Lab 04)** - the steepest local search restricted to candidate moves (moves that add at least one candidate edge), without LM.
5. **LM + candidate moves, k = 10** - the optional combination of both mechanisms: LM with new moves after each move, restricted to the candidate moves of method 4. Only candidate moves are generated (from the candidate lists, never by filtering the full neighbourhood) and evaluated, for the starting solution and after every move.

## The list of moves

A stored move keeps only node indices: a 2-opt move the two edges it removes, with the directions they had when it was evaluated (`a -> b`, `c -> d`, adding `(a, c)` and `(b, d)`); an exchange the removed node, its two neighbours and the inserted node. The delta depends only on these nodes, so it stays valid as long as the move can be applied. When LM is browsed from the best delta, a stored 2-opt move is:

1. **removed** from LM if one of its edges no longer exists;
2. **kept** in LM (and skipped) if both edges exist but in a different relative direction - it may become applicable later;
3. **applied** and removed from LM if both edges exist in the same relative direction (also both reversed).

An exchange is applied if the removed node still lies between the same two neighbours (in either order) and the inserted node is still not selected; otherwise it is removed.

Every pair of edges is evaluated in both reconnections: the one applicable now and the one with relatively inverted edges, which becomes applicable after another move reverses one of the edges. This includes the evaluation of the starting solution. In the experiment 31-32% of the 2-opt moves applied by LM had been evaluated with relatively inverted edges.

Among the applicable moves with the best delta, the one that comes first in the scan order of the reference search is applied (the baseline for LM on the full neighbourhood, the Lab 04 candidate search for LM + candidate moves). LM with new moves therefore applies the same moves as the baseline, and LM + candidate moves the same moves as the Lab 04 candidate search; both reach the same local optimum as their reference from every starting solution (verified for all 200 runs on both instances).

### LM + candidate moves

A 2-opt move adds two edges, each joining an endpoint of one removed edge with an endpoint of the other, and is a candidate move when at least one of them is a candidate edge `{x, w}`. The moves that add `{x, w}` remove one edge at `x` and one at `w`, which gives four of them: two applicable now and two with relatively inverted edges. They are generated directly from the candidate edges between selected nodes; a move that adds two candidate edges is generated once. Exchanges are generated from the candidates of the two neighbours of the removed node. After a move, only the candidate moves that involve a new edge or a node whose neighbours changed are generated, and the candidate exchanges that insert the node just removed next to one of its candidates. The exchange lists are sorted by `d(u, v) + cost(v)`: an exchange that enters `v` next to `u` changes the objective by at least that amount minus what it removes, so a scan stops at the first entry that cannot improve without losing any improving move. The candidate lists are those built by the Lab 04 solver.

## Implementation and performance

* **LM as a bucket queue.** Deltas are integers between `-(2 * max distance + max cost)` and `-1`, so LM is an array of buckets indexed by `-delta`, each a linked list of moves, with a bit mask of the non-empty buckets. Insertion takes constant time; browsing visits the moves in the order of delta without sorting. A stored move takes 16 bytes; its delta is given by its bucket.
* **Checks in constant time.** The successor of every node is stored (`-1` for unselected nodes), so `x -> y` is an edge exactly when `succ(x) == y`. Both move types are checked without branching on the type, which is unpredictable while browsing.
* **Evaluation.** The route has sentinel copies of its ends and cached edge lengths. Scans write every move into a buffer and keep only the improving ones without branches; exchange scans run over whole rows of the distance matrix four nodes at a time (SSE2), with a prohibitive insertion cost for selected nodes.
* **Memory.** The pool of moves and the buckets are allocated once per instance and reused by all runs; within a run the pool is append-only.
* **Verification.** After every run the objective is recomputed and compared with the accumulated deltas. The experiment also checks that the result of every LM run is a local optimum of the neighbourhood that was searched, repeats every run and checks that it gives the same result, and counts the runs that end in exactly the local optimum of the reference search.

On TSPA / TSPB the average time of a run is 0.77 / 0.78 ms for the (vectorised) full-neighbourhood baseline, 0.34 / 0.34 ms for LM with new moves (2.3x faster), 0.32 / 0.32 ms for the alternative algorithm, 0.46 / 0.50 ms for candidate moves and 0.29 / 0.31 ms for LM + candidate moves, the fastest method. LM with new moves computes 16x fewer deltas than the baseline. Most of its remaining time goes to inserting improving moves and checking them later: a random starting solution has about 9,800 improving moves (half of all moves), and about 99% of all moves inserted into LM are later removed because an edge or node is gone. LM + candidate moves computes 11-12x fewer deltas than LM with new moves, but is only about 1.1-1.2x faster, because candidate moves are generated from lists with irregular accesses and branches.

## Evaluation

Each method is run 200 times on TSPA and TSPB. Every run is timed 5 times from the same starting solution, interleaved with the runs of the other methods (for each starting cycle, every method once), so that changes of the processor clock affect all methods alike; the smallest of the 5 times counts, which suppresses interruptions by the operating system. Only the local search itself is timed. The one-time preparation per instance - building the candidate lists and creating LM (its memory is allocated once and reused by all runs) - is measured separately, in a loop of its own after the runs, as the median over all starting solutions and repetitions. Each method that needs it is also timed with all of its preparation done at the beginning of every run. The evaluation stores:

* `{TSPA,TSPB}_stats.csv` - `method_name,min,max,avg,sd` of the objective;
* `{TSPA,TSPB}_times.csv` - `method_name,average_ms,minimum_ms,maximum_ms,candidate_lists_ms,lm_memory_ms,prepared_average_ms`: the run times, the one-time preparation (0 where it does not apply) and the average time of a run that does its preparation at its beginning (empty if there is none);
* `{TSPA,TSPB}_work.csv` - per-run averages of the work counters:

  ```text
  method_name,applied,applied_two_opt,applied_inverted,evaluated,inserted,initial_inserted,checked,removed,not_applicable,full_evaluations,same_as_baseline,same_as_candidate
  ```

  `evaluated` is the number of deltas computed (for the baseline: (applied moves + 1) x 14,949 moves of the full neighbourhood), `inserted`/`initial_inserted` the moves added to LM in total and by the evaluation of the starting solution, `checked` the stored moves checked while browsing LM, of which `removed` were removed (situation 1) and `not_applicable` kept (situation 2), and `same_as_baseline` / `same_as_candidate` the number of runs ending in exactly the local optimum of the baseline / of the Lab 04 candidate search. Counters that do not apply to a method are empty;
* `results/` - best and worst closed routes of every method;
* `plots/` - SVG visualisations of the best and worst routes (used by the report).

## Build and run

From this directory:

```text
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
build/lab05.exe --seed 20260404
```

Running times are part of the results, so the build must be optimised; `CMakeLists.txt` defaults to `Release` (`-O3`). For GCC/Clang the instruction-set level is set by `LAB05_ARCH` (default `x86-64-v2`); `-DLAB05_ARCH=` keeps the compiler default. The executable accepts `TSPA` or `TSPB` to run one instance, `--data-dir DIR` to override the data location and `--seed N` for the starting solutions. The processor clock depends on the power state, so run the experiment with the laptop plugged in.

Evaluation artifacts are written to:

```text
lab-05-previous-deltas/evaluation/
```

The report is generated from the evaluation files with:

```text
python generate_report.py
```

It builds the report as HTML (`.report-build/report.html`) and prints it to `report.pdf` with a headless Chromium-based browser - Microsoft Edge or Google Chrome, or the one named by the `REPORT_BROWSER` environment variable; `--html-only` skips the PDF. The plots of the best solutions are taken from `evaluation/plots`. It also checks every reported best solution with the data and formulas of `problem-description/data/Solution checker.xlsx`. The generated report is available at:

```text
lab-05-previous-deltas/report.pdf
```
