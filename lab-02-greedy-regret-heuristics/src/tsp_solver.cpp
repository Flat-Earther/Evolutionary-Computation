#include "tsp_solver.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <stdexcept>

namespace {

constexpr int infinity = std::numeric_limits<int>::max();
constexpr double epsilon = 1e-9;

bool betterChoice(const TSPSolver::CandidateChoice& lhs, const TSPSolver::CandidateChoice& rhs, bool weighted) {
    if (lhs.node == -1) {
        return false;
    }
    if (rhs.node == -1) {
        return true;
    }

    if (weighted && std::abs(lhs.score - rhs.score) > epsilon) {
        return lhs.score > rhs.score;
    }
    if (!weighted && std::abs(lhs.regret - rhs.regret) > epsilon) {
        return lhs.regret > rhs.regret;
    }
    if (lhs.best.delta != rhs.best.delta) {
        return lhs.best.delta < rhs.best.delta;
    }
    if (lhs.regret != rhs.regret) {
        return lhs.regret > rhs.regret;
    }
    return lhs.node < rhs.node;
}

}  // namespace

TSPSolver::TSPSolver(const std::vector<std::vector<int>>& distance_matrix, const std::vector<Node>& nodes,
                     double regret_weight, double delta_weight, std::uint32_t seed)
    : distance_matrix_(distance_matrix),
      nodes_(nodes),
      target_count_(std::max(1, static_cast<int>(std::ceil(nodes.size() / 2.0)))),
      regret_weight_(regret_weight),
      delta_weight_(delta_weight),
      rng_(seed) {
    if (nodes_.empty()) {
        throw std::invalid_argument("instance must contain at least one node");
    }
    if (distance_matrix_.size() != nodes_.size()) {
        throw std::invalid_argument("distance matrix and nodes have different sizes");
    }
    if (regret_weight_ < 0.0 || delta_weight_ < 0.0 || (regret_weight_ == 0.0 && delta_weight_ == 0.0)) {
        throw std::invalid_argument("regret and delta weights must be non-negative and not both zero");
    }
}

Result TSPSolver::randomSolution() {
    std::vector<int> route(nodes_.size());
    std::iota(route.begin(), route.end(), 0);
    std::shuffle(route.begin(), route.end(), rng_);
    route.resize(static_cast<std::size_t>(target_count_));
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
        int best_delta = infinity;
        int next = -1;
        for (int node = 0; node < n; ++node) {
            if (used[node]) {
                continue;
            }
            const int delta = distance_matrix_[current][node] + nodes_[node].cost;
            if (delta < best_delta || (delta == best_delta && node < next)) {
                best_delta = delta;
                next = node;
            }
        }
        if (next == -1) {
            break;
        }
        route.push_back(next);
        used[next] = 1;
        current = next;
    }

    route.push_back(route.front());
    return {route, computeTotalCost(route)};
}

Result TSPSolver::nearestNeighborFlexible(int start_index) {
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> route{start_index};
    std::vector<char> used(n, 0);
    used[start_index] = 1;

    while (static_cast<int>(route.size()) < target_count_) {
        int best_delta = infinity;
        int best_node = -1;
        int best_position = -1;

        for (int node = 0; node < n; ++node) {
            if (used[node]) {
                continue;
            }
            for (const auto& option : pathInsertionOptions(route, node)) {
                if (option.delta < best_delta ||
                    (option.delta == best_delta && (best_node == -1 || node < best_node))) {
                    best_delta = option.delta;
                    best_node = node;
                    best_position = option.position;
                }
            }
        }

        if (best_node == -1) {
            break;
        }
        route.insert(route.begin() + best_position, best_node);
        used[best_node] = 1;
    }

    route.push_back(route.front());
    return {route, computeTotalCost(route)};
}

Result TSPSolver::greedyCycle(int start_index) {
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> route{start_index};
    std::vector<char> used(n, 0);
    used[start_index] = 1;

    if (target_count_ == 1) {
        route.push_back(route.front());
        return {route, computeTotalCost(route)};
    }

    int best_second = -1;
    int best_delta = infinity;
    for (int node = 0; node < n; ++node) {
        if (used[node]) {
            continue;
        }
        const int delta = 2 * distance_matrix_[start_index][node] + nodes_[node].cost;
        if (delta < best_delta || (delta == best_delta && (best_second == -1 || node < best_second))) {
            best_delta = delta;
            best_second = node;
        }
    }

    route.push_back(best_second);
    used[best_second] = 1;
    while (static_cast<int>(route.size()) < target_count_) {
        int selected_node = -1;
        int selected_position = -1;
        int selected_delta = infinity;

        for (int node = 0; node < n; ++node) {
            if (used[node]) {
                continue;
            }
            for (const auto& option : cycleInsertionOptions(route, node)) {
                if (option.delta < selected_delta ||
                    (option.delta == selected_delta && (selected_node == -1 || node < selected_node))) {
                    selected_delta = option.delta;
                    selected_node = node;
                    selected_position = option.position;
                }
            }
        }

        if (selected_node == -1) {
            break;
        }
        route.insert(route.begin() + selected_position, selected_node);
        used[selected_node] = 1;
    }

    route.push_back(route.front());
    return {route, computeTotalCost(route)};
}

Result TSPSolver::regret2Flexible(int start_index) {
    return buildRegretPath(start_index, false);
}

Result TSPSolver::regret2Cycle(int start_index) {
    return buildRegretCycle(start_index, false);
}

Result TSPSolver::weightedRegretFlexible(int start_index) {
    return buildRegretPath(start_index, true);
}

Result TSPSolver::weightedRegretCycle(int start_index) {
    return buildRegretCycle(start_index, true);
}

std::vector<TSPSolver::InsertionOption> TSPSolver::pathInsertionOptions(const std::vector<int>& path, int node) const {
    std::vector<InsertionOption> options;
    if (path.size() == 1) {
        options.push_back({distance_matrix_[path.front()][node] + nodes_[node].cost, 1});
        return options;
    }

    options.push_back({distance_matrix_[node][path.front()] + nodes_[node].cost, 0});
    options.push_back({distance_matrix_[path.back()][node] + nodes_[node].cost,
                      static_cast<int>(path.size())});
    for (int position = 1; position < static_cast<int>(path.size()); ++position) {
        const int before = path[position - 1];
        const int after = path[position];
        const int delta = distance_matrix_[before][node] + distance_matrix_[node][after]
                          - distance_matrix_[before][after] + nodes_[node].cost;
        options.push_back({delta, position});
    }
    return options;
}

std::vector<TSPSolver::InsertionOption> TSPSolver::cycleInsertionOptions(const std::vector<int>& cycle, int node) const {
    std::vector<InsertionOption> options;
    if (cycle.size() == 1) {
        options.push_back({2 * distance_matrix_[cycle.front()][node] + nodes_[node].cost, 1});
        return options;
    }

    options.reserve(cycle.size());
    for (int edge = 0; edge < static_cast<int>(cycle.size()); ++edge) {
        const int before = cycle[edge];
        const int after = cycle[(edge + 1) % cycle.size()];
        const int delta = distance_matrix_[before][node] + distance_matrix_[node][after]
                          - distance_matrix_[before][after] + nodes_[node].cost;
        options.push_back({delta, edge + 1});
    }
    return options;
}

Result TSPSolver::buildRegretPath(int start_index, bool weighted) {
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> path{start_index};
    std::vector<char> used(n, 0);
    used[start_index] = 1;

    while (static_cast<int>(path.size()) < target_count_) {
        CandidateChoice selected;
        for (int node = 0; node < n; ++node) {
            if (used[node]) {
                continue;
            }

            const auto options = pathInsertionOptions(path, node);
            CandidateChoice candidate;
            candidate.node = node;
            candidate.best = options.front();
            candidate.second = options.front();
            for (const auto& option : options) {
                if (option.delta < candidate.best.delta ||
                    (option.delta == candidate.best.delta && option.position < candidate.best.position)) {
                    candidate.second = candidate.best;
                    candidate.best = option;
                } else if (option.delta < candidate.second.delta ||
                           (option.delta == candidate.second.delta && option.position < candidate.second.position)) {
                    candidate.second = option;
                }
            }
            candidate.regret = static_cast<double>(candidate.second.delta - candidate.best.delta);
            candidate.score = regret_weight_ * candidate.regret
                              - delta_weight_ * static_cast<double>(candidate.best.delta);
            if (betterChoice(candidate, selected, weighted)) {
                selected = candidate;
            }
        }

        if (selected.node == -1) {
            break;
        }
        path.insert(path.begin() + selected.best.position, selected.node);
        used[selected.node] = 1;
    }

    path.push_back(path.front());
    return {path, computeTotalCost(path)};
}

Result TSPSolver::buildRegretCycle(int start_index, bool weighted) {
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> cycle{start_index};
    std::vector<char> used(n, 0);
    used[start_index] = 1;

    if (target_count_ == 1) {
        cycle.push_back(cycle.front());
        return {cycle, computeTotalCost(cycle)};
    }

    int second = -1;
    int best_delta = infinity;
    for (int node = 0; node < n; ++node) {
        if (used[node]) {
            continue;
        }
        const int delta = 2 * distance_matrix_[start_index][node] + nodes_[node].cost;
        if (delta < best_delta || (delta == best_delta && (second == -1 || node < second))) {
            best_delta = delta;
            second = node;
        }
    }
    cycle.push_back(second);
    used[second] = 1;

    while (static_cast<int>(cycle.size()) < target_count_) {
        CandidateChoice selected;
        for (int node = 0; node < n; ++node) {
            if (used[node]) {
                continue;
            }

            const auto options = cycleInsertionOptions(cycle, node);
            CandidateChoice candidate;
            candidate.node = node;
            candidate.best = options.front();
            candidate.second = options.front();
            for (const auto& option : options) {
                if (option.delta < candidate.best.delta ||
                    (option.delta == candidate.best.delta && option.position < candidate.best.position)) {
                    candidate.second = candidate.best;
                    candidate.best = option;
                } else if (option.delta < candidate.second.delta ||
                           (option.delta == candidate.second.delta && option.position < candidate.second.position)) {
                    candidate.second = option;
                }
            }
            candidate.regret = static_cast<double>(candidate.second.delta - candidate.best.delta);
            candidate.score = regret_weight_ * candidate.regret
                              - delta_weight_ * static_cast<double>(candidate.best.delta);
            if (betterChoice(candidate, selected, weighted)) {
                selected = candidate;
            }
        }

        if (selected.node == -1) {
            break;
        }
        cycle.insert(cycle.begin() + selected.best.position, selected.node);
        used[selected.node] = 1;
    }

    cycle.push_back(cycle.front());
    return {cycle, computeTotalCost(cycle)};
}

int TSPSolver::computeTotalCost(const std::vector<int>& route) const {
    int cost = 0;
    for (std::size_t i = 0; i + 1 < route.size(); ++i) {
        const int before = route[i];
        const int after = route[i + 1];
        cost += distance_matrix_[before][after] + nodes_[before].cost;
    }
    return cost;
}
