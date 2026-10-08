#pragma once

#include "node.hpp"

#include <random>
#include <vector>

struct Result {
    std::vector<int> route;
    int total_cost = 0;
};

class TSPSolver {
public:
    TSPSolver(const std::vector<std::vector<int>>& distance_matrix, const std::vector<Node>& nodes);

    Result randomSolution();
    Result nearestNeighborEnd(int start_index);
    Result nearestNeighborFlexible(int start_index);
    Result greedyCycle(int start_index);

    int targetCount() const { return target_count_; }

private:
    int computeTotalCost(const std::vector<int>& route) const;

    const std::vector<std::vector<int>>& distance_matrix_;
    const std::vector<Node>& nodes_;
    int target_count_;
    std::mt19937 rng_;
};
