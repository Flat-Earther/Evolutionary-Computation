#pragma once

#include "node.hpp"

#include <vector>

struct Result {
    std::vector<int> route;
    int total_cost = 0;
};

class TSPSolver {
public:
    TSPSolver(const std::vector<std::vector<int>>& distance_matrix, const std::vector<Node>& nodes,
              double regret_weight = 1.0, double delta_weight = 1.0);

    Result regret2Flexible(int start_index);
    Result regret2Cycle(int start_index);
    Result weightedRegretFlexible(int start_index);
    Result weightedRegretCycle(int start_index);

    int targetCount() const { return target_count_; }
    double regretWeight() const { return regret_weight_; }
    double deltaWeight() const { return delta_weight_; }

    // Exposed only so the deterministic tie-breaking helper can compare candidates.
    struct InsertionOption {
        int delta = 0;
        int position = -1;
    };

    struct CandidateChoice {
        int node = -1;
        InsertionOption best;
        InsertionOption second;
        double regret = 0.0;
        double score = 0.0;
    };

private:

    int computeTotalCost(const std::vector<int>& route) const;
    std::vector<InsertionOption> pathInsertionOptions(const std::vector<int>& path, int node) const;
    std::vector<InsertionOption> cycleInsertionOptions(const std::vector<int>& cycle, int node) const;
    Result buildRegretPath(int start_index, bool weighted);
    Result buildRegretCycle(int start_index, bool weighted);

    const std::vector<std::vector<int>>& distance_matrix_;
    const std::vector<Node>& nodes_;
    int target_count_;
    double regret_weight_;
    double delta_weight_;
};
