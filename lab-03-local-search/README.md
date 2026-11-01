# Lab 03 - Local Search

This laboratory implements local search for the Traveling Salesperson Problem with Node Costs. A feasible solution selects exactly `ceil(n / 2)` nodes and arranges them into a closed Hamiltonian cycle while minimizing:

```text
objective = cycle length + costs of selected nodes
```

The implementation uses the same distance matrix, node-cost representation, solution checker conventions, and TSPA/TSPB instances as Labs 01 and 02.

## Implemented variants

The assignment combines three binary choices:

1. **Starting solution**
   - Random feasible solution
   - Best constructive solution found from the Lab 01/02 greedy and regret constructors for a given start node
2. **Local-search strategy**
   - Steepest descent: evaluate the whole neighborhood and apply the best improving move
   - Greedy local search: randomize the neighborhood and apply the first improving move
3. **Intra-route neighborhood**
   - Node exchange: swap two selected nodes in the route order
   - 2-opt exchange: reverse a route segment and reconnect the two boundary edges

Every variant also includes an inter-route node exchange, replacing one selected node with one unselected node. This lets local search improve both the order of selected nodes and the selected subset itself.

The three choices produce eight methods:

| Method | Start | Strategy | Intra-route move |
| --- | --- | --- | --- |
| Random / steepest / node exchange | Random | Steepest | Node exchange |
| Random / steepest / 2-opt | Random | Steepest | 2-opt |
| Random / greedy / node exchange | Random | Greedy | Node exchange |
| Random / greedy / 2-opt | Random | Greedy | 2-opt |
| Greedy / steepest / node exchange | Best previous construction | Steepest | Node exchange |
| Greedy / steepest / 2-opt | Best previous construction | Steepest | 2-opt |
| Greedy / greedy / node exchange | Best previous construction | Greedy | Node exchange |
| Greedy / greedy / 2-opt | Best previous construction | Greedy | 2-opt |

## Move evaluation

The implementation evaluates each candidate using the direct change in the objective function. It does not construct a complete neighbor and recalculate the objective from scratch, and it does not reuse deltas across iterations or use candidate-move lists from later assignments.

The accepted move must have a strictly negative delta. Local search terminates when no improving move remains in the selected neighborhood.

## Evaluation

Each method is run 200 times for both TSPA and TSPB. Random-start methods generate a new random feasible cycle. Greedy-start methods use each of the 200 nodes as the starting node for the best constructive solution inherited from the previous laboratories.

For every method and instance, the evaluation stores:

* minimum objective value
* maximum objective value
* average objective value
* standard deviation
* total runtime
* best and worst closed routes
* best and worst SVG visualizations

The executable also validates every result as a closed route containing exactly 100 distinct zero-based node indices. After every local-search run, the objective recomputed from the final route is checked against the accumulated move deltas.

The generated artifacts are stored in:

```text
lab-03-local-search/evaluation/
```

The report includes a new comparison table before the legacy detailed tables. The comparison table contains every method from Labs 01, 02, and 03 in the format:

```text
average(minimum - maximum)
```

The best average method for each instance is highlighted. The detailed minimum/maximum/average/standard-deviation tables from the previous reports are retained afterwards.

## Build and run

From this directory:

```text
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
build/lab03.exe --seed 303
```

The executable accepts `TSPA` or `TSPB` to run one instance and `--data-dir DIR` to override the data location.

The report is generated with:

```text
python generate_report.py
```

The final report is available as [`report.pdf`](report.pdf).
