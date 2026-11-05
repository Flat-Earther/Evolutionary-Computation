#pragma once

#include "node.hpp"

#include <random>
#include <vector>

struct Result {
    std::vector<int> route;
    int total_cost = 0;
};

enum class CandidateRanking {
    DistanceIntraPlusCostsInter,
    DistancePlusNodeCostsForAll,
};

class TSPSolver {
public:
    TSPSolver(const std::vector<std::vector<int>>& distance_matrix, const std::vector<Node>& nodes,
              int candidate_count = 10,
              CandidateRanking candidate_ranking = CandidateRanking::DistanceIntraPlusCostsInter);

    Result randomStartingSolution(std::mt19937& rng) const;
    Result steepestLocalSearch(const Result& initial, bool use_candidate_moves) const;

    int targetCount() const { return target_count_; }

private:
    enum class MoveType {
        TwoOpt,
        InterNodeExchange,
    };

    struct Move {
        MoveType type;
        int first;
        int second;
    };

    int objective(const std::vector<int>& route) const;
    Result makeResult(const std::vector<int>& open_route) const;

    void buildCandidateLists(int candidate_count);
    std::vector<Move> fullNeighborhood(const std::vector<int>& route) const;
    std::vector<Move> candidateNeighborhood(const std::vector<int>& route) const;
    int moveDelta(const std::vector<int>& route, const Move& move) const;
    void applyMove(std::vector<int>& route, const Move& move) const;

    const std::vector<std::vector<int>>& distance_matrix_;
    const std::vector<Node>& nodes_;
    CandidateRanking candidate_ranking_;
    std::vector<std::vector<int>> intra_candidates_;
    std::vector<std::vector<int>> inter_candidates_;
    int target_count_;
};
