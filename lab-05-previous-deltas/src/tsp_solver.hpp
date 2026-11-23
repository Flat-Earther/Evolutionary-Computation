#pragma once

#include "distance_matrix.hpp"

#include <cstdint>
#include <random>
#include <vector>

struct Result {
    std::vector<int> route;  // closed cycle: the first node is repeated at the end
    int total_cost = 0;
};

// How the other vertices v are ranked when the "nearest" vertices of u are chosen as its
// candidates. The cost of u itself would add the same amount to every score, so it is left
// out; ties go to the smaller vertex index.
enum class NearestMetric {
    Distance,          // d(u, v)
    Cost,              // cost(v)
    DistancePlusCost,  // d(u, v) + cost(v)
};

// Ranking used for the candidate edges of each move type.
struct CandidateDefinition {
    NearestMetric intra = NearestMetric::Distance;          // 2-opt moves
    NearestMetric inter = NearestMetric::DistancePlusCost;  // selected/unselected exchanges
};

// Steepest local search in the neighbourhood made of 2-opt moves (intra-route) and
// selected/unselected node exchanges (inter-route), either complete or restricted to
// candidate moves. Only the distance matrix and the node costs are accessed.
//
// Every iteration applies the move with the lowest delta; ties are broken by a fixed move
// order (the scan order of a straightforward implementation that materialises the
// neighbourhood), so a run is fully determined by its starting solution and gives exactly
// the same local optimum as that straightforward implementation, only faster.
class TSPSolver {
public:
    TSPSolver(const DistanceMatrix& distances, std::vector<int> node_costs, int candidate_count = 10,
              CandidateDefinition candidate_definition = {});

    Result randomStartingSolution(std::mt19937& rng) const;
    // applied_moves, if given, is increased by the number of moves applied by the run.
    Result steepestLocalSearch(const Result& initial, bool use_candidate_moves,
                               long long* applied_moves = nullptr) const;

    int targetCount() const { return target_count_; }
    // Wall-clock time the constructor spent building the candidate lists (choosing the
    // nearest vertices and preparing the lists for the search).
    double candidateListMilliseconds() const { return candidate_list_ms_; }

private:
    enum class MoveType {
        None,
        TwoOpt,    // reverse the route segment [first, second]
        Exchange,  // replace the node at position first with the unselected node second
    };

    struct Move {
        int delta = 0;
        MoveType type = MoveType::None;
        int first = 0;
        int second = 0;
    };

    // Entry of a candidate list owned by node u. The weight is the part of a move delta
    // that depends only on u and the candidate, so it is computed once per instance.
    struct Candidate {
        int node;
        int weight;  // intra lists: d(u, node); inter lists: d(u, node) + cost(node)
    };

    // Symmetric candidate lists in compressed sparse row form: the candidates of node u are
    // entries [offsets[u], offsets[u + 1]), sorted by node index or by weight. rank[e] is the
    // index of entry e among u's candidates ordered by node index (used to break ties).
    // During the search every list is paired with a bitmask (one bit per entry, words
    // [words[u], words[u + 1])). Because the lists are symmetric, the entry (u -> v) has a
    // mirror entry (v -> u); mirror_bit holds the bit index of that mirror entry, so when the
    // selection status of u changes, the bits that describe u in the lists of all its
    // candidates can be flipped directly.
    struct CandidateLists {
        std::vector<int> offsets;
        std::vector<Candidate> entries;
        std::vector<int> rank;
        std::vector<int> words;
        std::vector<int> mirror_bit;
    };

    class Search;

    int objective(const std::vector<int>& open_route) const;
    Result makeResult(const std::vector<int>& open_route) const;
    void buildCandidateLists(int candidate_count, CandidateDefinition candidate_definition);
    CandidateLists packCandidateLists(const std::vector<char>& is_candidate, bool add_node_cost,
                                      bool sort_by_weight) const;

    const DistanceMatrix& distances_;
    std::vector<int> costs_;
    int node_count_;
    int target_count_;
    CandidateLists intra_;  // 2-opt candidates by node index; only selected entries are scanned
    CandidateLists inter_;  // exchange candidates by weight; only unselected entries are scanned
    double candidate_list_ms_ = 0.0;
};
