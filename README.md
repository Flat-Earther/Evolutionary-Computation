# Hamiltonian Cycle Optimization

A collection of optimization algorithms for solving a **Hamiltonian Cycle selection problem** with node costs.

## Problem

Given a set of nodes represented by their `(x, y)` coordinates and an individual cost for each node, the goal is to:

1. Select exactly **50% of the nodes** (rounded up when the number of nodes is odd).
2. Construct a **Hamiltonian cycle** passing through all selected nodes.
3. Minimize the objective function:

**total cycle length + total cost of selected nodes**

The distance between two nodes is their Euclidean distance, mathematically rounded to the nearest integer.

Before optimization begins, the complete distance matrix is calculated from the input coordinates. Optimization algorithms operate exclusively on this distance matrix and node costs, making them independent of the original node coordinates.

## Implemented Algorithms

The project contains multiple approaches to the problem, including:

* Random search
* Greedy heuristics
* Dynamic programming
* Population-based algorithms
* Evolutionary algorithms
* Ant Colony Optimization
* Other heuristic and metaheuristic approaches

Each algorithm can be evaluated and compared using the same problem instances and objective function.

## Input

An instance consists of three columns:

```text
x    y    cost
10   25   15
32   18   20
...
```

The first two columns represent node coordinates, while the third column specifies the cost of selecting the node.

The coordinates are used only during the initial construction of the distance matrix. After that, optimization methods work exclusively with the resulting distance matrix and node costs.

## Objective Function

For a solution selecting nodes:

```text
S = {v₁, v₂, ..., vₖ}
```

where `k = ceil(n / 2)`, the objective value is:

```text
f(S) = cycle_length(S) + Σ cost(v)
                                  v ∈ S
```

The objective is to **minimize** `f(S)`.

## Project Goals

The main purpose of the project is to investigate and compare different optimization techniques for the same combinatorial optimization problem.

The algorithms can be compared in terms of:

* Solution quality
* Execution time
* Convergence behaviour
* Robustness across different instances
* Scalability with increasing instance size

## Technologies

* Java
* Maven
* Git / GitHub

## Project Structure

```text
src/
├── main/
│   └── ...
└── test/
    └── ...

instances/
└── ...

results/
└── ...
```

## Course

This project was developed as part of the **Evolutionary Computation** course at **Poznań University of Technology**.
