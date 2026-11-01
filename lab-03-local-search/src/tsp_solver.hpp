#pragma once

#include "node.hpp"

#include <random>
#include <vector>

struct Result {
    std::vector<int> route;
    int total_cost = 0;
};

enum class SearchStrategy {
    Steepest,
    Greedy,
};

enum class IntraNeighborhood {
    NodeExchange,
    TwoOpt,
};

class TSPSolver {
public:
    TSPSolver(const std::vector<std::vector<int>>& distance_matrix, const std::vector<Node>& nodes);

    Result randomStartingSolution(std::mt19937& rng) const;
    Result bestGreedyStartingSolution(int start_index) const;
    Result localSearch(const Result& initial, SearchStrategy strategy, IntraNeighborhood neighborhood,
                       std::mt19937& rng) const;

    int targetCount() const { return target_count_; }

private:
    enum class MoveType {
        IntraNodeExchange,
        TwoOpt,
        InterNodeExchange,
    };

    struct Move {
        MoveType type;
        int first;
        int second;
    };

    struct InsertionOption {
        int delta = 0;
        int position = -1;
    };

    struct CandidateChoice {
        int node = -1;
        InsertionOption best;
        double regret = 0.0;
        double score = 0.0;
    };

    static bool betterChoice(const CandidateChoice& lhs, const CandidateChoice& rhs, bool weighted);
    int objective(const std::vector<int>& route) const;
    std::vector<Move> neighborhood(const std::vector<int>& route, IntraNeighborhood intra) const;
    int moveDelta(const std::vector<int>& route, const Move& move) const;
    void applyMove(std::vector<int>& route, const Move& move) const;
    Result makeResult(const std::vector<int>& open_route) const;

    std::vector<InsertionOption> pathInsertionOptions(const std::vector<int>& path, int node) const;
    std::vector<InsertionOption> cycleInsertionOptions(const std::vector<int>& cycle, int node) const;
    Result buildRegretPath(int start_index, bool weighted) const;
    Result buildRegretCycle(int start_index, bool weighted) const;

    const std::vector<std::vector<int>>& distance_matrix_;
    const std::vector<Node>& nodes_;
    int target_count_;
};
