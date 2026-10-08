#include "tsp_solver.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <random>

TSPSolver::TSPSolver(const std::vector<std::vector<int>>& distance_matrix, const std::vector<Node>& nodes)
    : distance_matrix_(distance_matrix),
      nodes_(nodes),
      target_count_(std::max(2, static_cast<int>(std::ceil(nodes.size() / 2.0)))),
      rng_(std::random_device{}()) {}

Result TSPSolver::randomSolution() {
    std::vector<int> route(nodes_.size());
    std::iota(route.begin(), route.end(), 0);
    std::shuffle(route.begin(), route.end(), rng_);
    route.resize(target_count_);
    route.push_back(route.front());
    return {route, computeTotalCost(route)};
}

Result TSPSolver::nearestNeighborEnd(int start_index) {
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> route;
    std::vector<char> used(n, 0);
    route.push_back(start_index);
    used[start_index] = 1;
    int current = start_index;

    while (static_cast<int>(route.size()) < target_count_) {
        int best_dist = std::numeric_limits<int>::max();
        int next = -1;
        for (int i = 0; i < n; ++i) {
            if (used[i]) {
                continue;
            }
            const int d = distance_matrix_[current][i] + nodes_[i].cost;
            if (d < best_dist) {
                best_dist = d;
                next = i;
            }
        }
        if (next == -1) {
            break;
        }
        route.push_back(next);
        used[next] = 1;
        current = next;
    }

    route.push_back(start_index);
    return {route, computeTotalCost(route)};
}

Result TSPSolver::nearestNeighborFlexible(int start_index) {
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> route{start_index, start_index};
    std::vector<char> used(n, 0);
    used[start_index] = 1;
    int used_count = 1;

    while (used_count < target_count_) {
        int best_increase = std::numeric_limits<int>::max();
        int best_node = -1;
        int best_pos = -1;

        for (int node = 0; node < n; ++node) {
            if (used[node]) {
                continue;
            }
            for (int pos = 0; pos < static_cast<int>(route.size()) - 1; ++pos) {
                const int a = route[pos];
                const int b = route[pos + 1];
                const int increase = distance_matrix_[a][node] + distance_matrix_[node][b]
                                     - distance_matrix_[a][b] + nodes_[node].cost;
                if (increase < best_increase) {
                    best_increase = increase;
                    best_node = node;
                    best_pos = pos + 1;
                }
            }
        }

        if (best_node == -1) {
            break;
        }
        route.insert(route.begin() + best_pos, best_node);
        used[best_node] = 1;
        ++used_count;
    }

    return {route, computeTotalCost(route)};
}

Result TSPSolver::greedyCycle(int start_index) {
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> route;
    std::vector<char> used(n, 0);
    used[start_index] = 1;
    route.push_back(start_index);

    int best_second = -1;
    int min_obj = std::numeric_limits<int>::max();
    for (int i = 0; i < n; ++i) {
        if (used[i]) {
            continue;
        }
        const int obj = 2 * distance_matrix_[start_index][i] + nodes_[start_index].cost + nodes_[i].cost;
        if (obj < min_obj) {
            min_obj = obj;
            best_second = i;
        }
    }

    if (best_second == -1) {
        return {route, 0};
    }
    route.push_back(best_second);
    used[best_second] = 1;

    while (static_cast<int>(route.size()) < target_count_) {
        int best_node = -1;
        int best_pos = -1;
        int best_increase = std::numeric_limits<int>::max();

        for (int i = 0; i < n; ++i) {
            if (used[i]) {
                continue;
            }
            for (int j = 0; j < static_cast<int>(route.size()); ++j) {
                const int a = route[j];
                const int b = route[(j + 1) % route.size()];
                const int increase = distance_matrix_[a][i] + distance_matrix_[i][b]
                                     - distance_matrix_[a][b] + nodes_[i].cost;
                if (increase < best_increase) {
                    best_increase = increase;
                    best_node = i;
                    best_pos = j + 1;
                }
            }
        }

        if (best_node == -1) {
            break;
        }
        route.insert(route.begin() + best_pos, best_node);
        used[best_node] = 1;
    }

    route.push_back(route.front());
    return {route, computeTotalCost(route)};
}

int TSPSolver::computeTotalCost(const std::vector<int>& route) const {
    int cost = 0;
    for (std::size_t i = 0; i + 1 < route.size(); ++i) {
        const int a = route[i];
        const int b = route[i + 1];
        cost += distance_matrix_[a][b] + nodes_[a].cost;
    }
    return cost;
}
