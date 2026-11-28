#pragma once

#include "lm_search.hpp"
#include "tsp_solver.hpp"

#include <random>
#include <string>
#include <vector>

// Perturbation of ILS, applied to the current local optimum in this order:
//   1. `double_bridges` double-bridge moves: the route S = A B C D, cut at three random positions,
//      becomes A C B D (two neighbouring segments swap places, none is reversed);
//   2. replacement of a segment: `segment_length` consecutive selected nodes, starting at a random
//      position, are replaced by distinct random nodes that were not selected;
//   3. `random_moves` random moves of the local-search neighbourhood: each, with probability 1/2,
//      a random 2-opt move (reverse S[i..j] for random i < j) or a random exchange (a random
//      selected node replaced by a random not selected node).
struct Perturbation {
    std::string id;
    std::string label;
    int double_bridges = 1;
    int segment_length = 4;
    int random_moves = 0;
};

// One run of multiple start local search.
struct MslsRun {
    Result best;
    double ms = 0;
    std::vector<int> local_optima;        // objective of every local-search run
    std::vector<double> local_search_ms;  // time of every local-search run (with its random start)
};

// One run of iterated local search.
struct IlsRun {
    Result best;
    double ms = 0;
    long long local_searches = 0;  // runs of the basic local search, the first one included
    long long improvements = 0;    // perturbations whose local optimum was accepted
};

// MSLS and ILS around the steepest local search (2-opt and exchange of a selected and a not
// selected node), implemented with the list of improving moves of assignment 5 (it applies the same
// moves as the plain steepest local search).
class LocalSearchMethods {
public:
    LocalSearchMethods(const TSPSolver& solver, MoveListSearch& local_search, int node_count);

    // `iterations` runs of local search, each from a new random solution; the best local optimum.
    MslsRun multipleStart(int iterations, std::mt19937& rng);

    // Local search from a random solution, then until `time_limit_ms` has passed: perturb the
    // current solution x, run local search from the result y, and accept y if f(y) < f(x).
    IlsRun iterated(double time_limit_ms, const Perturbation& perturbation, std::mt19937& rng);

    // Applies the perturbation to an open route (the selected nodes in cycle order).
    void perturb(std::vector<int>& route, const Perturbation& perturbation, std::mt19937& rng);

private:
    Result localSearch(const std::vector<int>& open_route);
    void doubleBridge(std::vector<int>& route, std::mt19937& rng);
    void replaceSegment(std::vector<int>& route, int length, std::mt19937& rng);
    void randomMove(std::vector<int>& route, std::mt19937& rng);
    void markSelection(const std::vector<int>& route);

    const TSPSolver& solver_;
    MoveListSearch& local_search_;
    int node_count_;
    std::vector<char> selected_;  // scratch: selection of the route being perturbed
    std::vector<int> pool_;       // scratch: candidate nodes to insert
    std::vector<int> buffer_;     // scratch: route being rebuilt
};
