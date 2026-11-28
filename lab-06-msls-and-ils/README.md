# Lab 06 - Multiple Start Local Search and Iterated Local Search

This laboratory extends the steepest local search in two simple ways: multiple start local search (MSLS) and iterated local search (ILS). Both use the local search with the list of improving moves (LM) of Lab 05, in the variant that evaluates the new moves after each move: the steepest local search with 2-opt as the intra-route move and the exchange of a selected and an unselected node as the inter-route move. The LM sources (`src/lm_search.{hpp,cpp}`) are those of Lab 05, unchanged; LM applies exactly the same moves as the plain steepest local search, about 2.3x faster. The plain steepest local search is used only to verify that every reported solution is a local optimum.

## Methods

1. **Multiple start local search (MSLS)** - 400 runs of the local search, each from a new random solution; the result of one run of MSLS is the best of the 400 local optima.
2. **Iterated local search (ILS)** - the local search from one random solution, then, until the time limit: perturb the current solution, run the local search from the perturbed solution and accept the new local optimum if it is strictly better. The time limit is the average running time of MSLS on the same instance, measured in the same execution.

Each method is run 20 times per instance.

## Perturbation

Every iteration of ILS applies, to a copy of the current local optimum `S = S[0..m-1]`:

1. **one double bridge** - three distinct cut positions `0 < i < j < k <= m - 1` are drawn uniformly and `S = A B C D` (`A = S[0..i-1]`, `B = S[i..j-1]`, `C = S[j..k-1]`, `D = S[k..m-1]`) becomes `A C B D`. The segments `B` and `C` swap places without being reversed, which a single 2-opt move cannot undo;
2. **the replacement of a segment of 4 nodes** - a start position `p` is drawn uniformly, and the nodes at positions `p, p+1, p+2, p+3` (cyclically) are replaced by distinct nodes drawn uniformly from the nodes that were not selected before this step, in the order of drawing. This changes the selection of nodes.

With `--perturbation-experiment`, ILS is also run 20 times per instance with six other perturbations and the same time limit: the double bridge alone, the segment replacement alone, 10 random moves (each a random 2-opt move or a random exchange), a double bridge with a segment of 2 or 8 nodes, and two double bridges with a segment of 4 nodes. The chosen perturbation is reported with the main ILS series.

## Results

| Instance | MSLS: average (min - max) | ILS: average (min - max) | Local searches per ILS run |
| -------- | ------------------------- | ------------------------ | -------------------------- |
| TSPA     | 73,584.35 (73,079 - 73,986) | 71,587.85 (71,484 - 71,960) | 3,746.85 (3,403 - 3,951) |
| TSPB     | 50,086.90 (49,495 - 50,557) | 48,251.05 (48,150 - 48,564) | 3,667.65 (3,052 - 3,964) |

The time limit of ILS was 152.9 ms (TSPA) and 158.9 ms (TSPB). Every ILS run was better than the best MSLS run on both instances. ILS performs about 9x as many local searches as MSLS (400) in the same time, because a local search from a perturbed local optimum needs only a few moves.

## Evaluation

The evaluation stores:

* `{TSPA,TSPB}_stats.csv` - `method_name,min,max,avg,sd` of the objective for `local_search` (all 8,000 single local searches performed inside MSLS, each from a random solution), `msls` and `ils`;
* `{TSPA,TSPB}_times.csv` - `method_name,average_ms,minimum_ms,maximum_ms,time_limit_ms`: the running time of one run (for `local_search`, one local search including the generation of its random solution) and the time limit of ILS;
* `{TSPA,TSPB}_ls_runs.csv` - `method_name,average,minimum,maximum,improvements_average`: the number of local searches in one run (for ILS including the first one) and the average number of accepted perturbations;
* `{TSPA,TSPB}_runs.csv` - `method_name,run,objective,time_ms,local_searches,improvements` of every run of MSLS and ILS;
* `{TSPA,TSPB}_perturbations.csv` - written with `--perturbation-experiment`:

  ```text
  perturbation,label,double_bridges,segment_length,random_moves,min,max,avg,sd,ls_runs_average,ls_runs_minimum,ls_runs_maximum
  ```

* `results/` - best and worst closed routes of MSLS and ILS;
* `plots/` - SVG visualisations of the best and worst routes (used by the report).

Every reported solution is checked: it must be a valid cycle of 100 distinct nodes, its objective is recomputed from scratch, and a run of the steepest local search from it must not find an improving move.

## Build and run

From this directory:

```text
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
build/lab06.exe --seed 20260404 --perturbation-experiment
```

Running times are part of the method (ILS gets the average time of MSLS), so the build must be optimised; `CMakeLists.txt` defaults to `Release` (`-O3`). For GCC/Clang the instruction-set level is set by `LAB06_ARCH` (default `x86-64-v2`); `-DLAB06_ARCH=` keeps the compiler default. The executable accepts `TSPA` or `TSPB` to run one instance, `--data-dir DIR` to override the data location, `--seed N` for the random generators and `--perturbation-experiment` for the comparison of perturbations. Every run of MSLS and ILS has its own random generator seeded from the seed, the instance and the run; ILS stops after a time, so its results can differ slightly between executions. The full experiment takes about a minute. The processor clock depends on the power state, so run it with the laptop plugged in.

Evaluation artifacts are written to:

```text
lab-06-msls-and-ils/evaluation/
```

The report is generated from the evaluation files with:

```text
python generate_report.py
```

It needs the files of the run with `--perturbation-experiment`, and it reads the results of the best construction heuristics and local search of Labs 02, 02.5 and 03 from their `evaluation/` directories. It builds the report as HTML (`.report-build/report.html`) and prints it to `report.pdf` with a headless Chromium-based browser - Microsoft Edge or Google Chrome, or the one named by the `REPORT_BROWSER` environment variable; `--html-only` skips the PDF. The plots of the best solutions are taken from `evaluation/plots`. It also checks every reported best solution with the data and formulas of `problem-description/data/Solution checker.xlsx`. The generated report is available at:

```text
lab-06-msls-and-ils/report.pdf
```
