# Lab 04 - Candidate Moves

This laboratory accelerates the steepest local search from Lab 03 by evaluating only candidate moves. The selected neighborhood is the 2-opt intra-route neighborhood together with selected-to-unselected node exchange.

## Methods and parameter experiment

The experiment evaluates the full-neighborhood baseline and a candidate-move method for several candidate-list sizes. By default it tests `k = 1, 5, 10, 15, 20, 30, 50`. The `k = 1` case uses only the single nearest candidate edge from each endpoint. All methods use the same 200 pre-generated random starting cycles for a given instance:

1. **Steepest local search - full neighborhood**
   - evaluates every valid 2-opt move;
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

## Evaluation and timing

Each method and each candidate-list size is run 200 times for TSPA and TSPB. The same random starting cycles are used for all methods of a given instance. The evaluation stores:

* objective minimum, maximum, average, and standard deviation;
* best and worst closed routes;
* best and worst SVG visualizations;
* per-run runtime average, minimum, and maximum in milliseconds.

The runtime CSV files use the following format:

```text
method_name,candidate_count,average_ms,minimum_ms,maximum_ms
```

## Additional ranking experiment

The additional experiment compares the current candidate ranking with a variant that also includes node costs when ranking intra-route candidate edges:

1. **Distance intra, node costs inter** - the default policy: intra-route candidates are ordered by distance, while inter-route candidates are ordered by distance plus the costs of both vertices.
2. **Distance plus node costs intra/inter** - candidates for both move types are ordered by distance plus the costs of both vertices.

Both policies are evaluated for `k = 1, 5, 10, 15, 20, 30, 50`. For each instance, policy, and candidate-list size, the same 200 random starting cycles are used, so the comparison isolates the effect of the ranking rule. The results are written to `TSPA_ranking_stats.csv`, `TSPA_ranking_times.csv`, `TSPB_ranking_stats.csv`, and `TSPB_ranking_times.csv`.

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

The executable accepts `TSPA` or `TSPB` to run one instance, `--data-dir DIR` to override the data location, and `--candidate-counts K1,K2,...` to select the candidate-list sizes. For example:

```text
build/lab04.exe --candidate-counts 1,5,10,15,20,30,50 --seed 20260404
```

The singular `--candidate-count K` option remains available for running one candidate-list size.

Evaluation artifacts are written to:

```text
lab-04-candidate-moves/evaluation/
```

The generated report is available at:

```text
lab-04-candidate-moves/report.pdf
```
