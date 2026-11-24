#pragma once

#include "distance_matrix.hpp"
#include "tsp_solver.hpp"

#include <memory>
#include <vector>

// Steepest local search (2-opt + exchange of a selected and a not selected node) that reuses
// move evaluations from previous iterations. Improving moves are kept in a list LM ordered by
// delta; a stored move is applied later without being evaluated again, as long as the edges it
// removes still exist in the solution with the same relative direction.
enum class MoveListVariant {
    // After every applied move only the new moves - those that involve an edge or a node changed
    // by the move - are evaluated and added to LM. LM therefore always contains every improving
    // move, and the search takes exactly the same path as the plain steepest local search.
    NewMoves,
    // The alternative algorithm of the assignment: moves are evaluated only when LM contains no
    // applicable move, and then the whole neighbourhood is evaluated again.
    Alternative,
};

// Work done by one run.
struct MoveListCounters {
    long long evaluated = 0;         // move deltas computed
    long long inserted = 0;          // moves added to LM
    long long initial_inserted = 0;  // ... by the evaluation of the starting solution
    long long checked = 0;           // stored moves checked while browsing LM
    long long removed = 0;           // ... of which removed: a removed edge no longer exists
    long long not_applicable = 0;    // ... of which kept: edges exist in a different relative direction
    long long full_evaluations = 0;  // evaluations of the whole neighbourhood
    long long applied = 0;           // moves applied
    long long applied_two_opt = 0;   // ... of which 2-opt moves
    long long applied_inverted = 0;  // ... of which evaluated with relatively inverted edges
};

// Candidate lists for the search restricted to candidate moves: the candidates of every node,
// each list sorted by node index (see TSPSolver::candidateNeighbours). The lists must be
// symmetric: v is a candidate of u exactly when u is a candidate of v.
struct CandidateSets {
    std::vector<std::vector<int>> intra;  // 2-opt (intra-route) candidates
    std::vector<std::vector<int>> inter;  // exchange (inter-route) candidates
};

class MoveListSearch {
public:
    // The whole neighbourhood: every 2-opt move and every exchange.
    MoveListSearch(const DistanceMatrix& distances, std::vector<int> node_costs);
    // Restricted to candidate moves, as in assignment 4: moves that add at least one candidate
    // edge (intra candidates for 2-opt, inter candidates for exchanges). The moves are generated
    // from the candidate lists, and ties between equal deltas are broken in the scan order of the
    // assignment-4 candidate search, so the search applies the same moves as that search.
    MoveListSearch(const DistanceMatrix& distances, std::vector<int> node_costs, const CandidateSets& candidates);
    ~MoveListSearch();
    MoveListSearch(const MoveListSearch&) = delete;
    MoveListSearch& operator=(const MoveListSearch&) = delete;

    // Runs the search from `initial` (a closed route); `counters`, if given, receives the work
    // done by the run. LM and the other buffers are kept between runs, so one object must not be
    // used by several threads at the same time.
    Result run(const Result& initial, MoveListVariant variant, MoveListCounters* counters = nullptr);

    int targetCount() const { return target_count_; }

private:
    class State;

    void initialise(const CandidateSets* candidates);

    const DistanceMatrix& distances_;
    std::vector<int> costs_;
    int node_count_;
    int target_count_;
    std::unique_ptr<State> state_;
};
