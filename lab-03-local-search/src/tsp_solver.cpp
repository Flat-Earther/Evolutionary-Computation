#include "tsp_solver.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <set>
#include <stdexcept>

namespace {

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
    return lhs.node < rhs.node;
}

}  // namespace

TSPSolver::TSPSolver(const std::vector<std::vector<int>>& distance_matrix, const std::vector<Node>& nodes)
    : distance_matrix_(distance_matrix),
      nodes_(nodes),
      target_count_(std::max(1, static_cast<int>(std::ceil(nodes.size() / 2.0)))) {
    if (nodes_.empty() || distance_matrix_.size() != nodes_.size()) {
        throw std::invalid_argument("invalid instance or distance matrix");
    }
}

int TSPSolver::objective(const std::vector<int>& route) const {
    if (route.empty()) {
        return 0;
    }
    int total = 0;
    for (std::size_t i = 0; i < route.size(); ++i) {
        total += nodes_[route[i]].cost;
        total += distance_matrix_[route[i]][route[(i + 1) % route.size()]];
    }
    return total;
}

Result TSPSolver::makeResult(const std::vector<int>& open_route) const {
    if (open_route.empty()) {
        throw std::invalid_argument("cannot create a result from an empty route");
    }
    std::vector<int> closed = open_route;
    closed.push_back(closed.front());
    return {closed, objective(open_route)};
}

Result TSPSolver::randomStartingSolution(std::mt19937& rng) const {
    std::vector<int> nodes(nodes_.size());
    std::iota(nodes.begin(), nodes.end(), 0);
    std::shuffle(nodes.begin(), nodes.end(), rng);
    nodes.resize(static_cast<std::size_t>(target_count_));
    return makeResult(nodes);
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
        options.push_back({distance_matrix_[before][node] + distance_matrix_[node][after]
                               - distance_matrix_[before][after] + nodes_[node].cost,
                           position});
    }
    return options;
}

std::vector<TSPSolver::InsertionOption> TSPSolver::cycleInsertionOptions(const std::vector<int>& cycle, int node) const {
    std::vector<InsertionOption> options;
    for (int edge = 0; edge < static_cast<int>(cycle.size()); ++edge) {
        const int before = cycle[edge];
        const int after = cycle[(edge + 1) % cycle.size()];
        options.push_back({distance_matrix_[before][node] + distance_matrix_[node][after]
                               - distance_matrix_[before][after] + nodes_[node].cost,
                           edge + 1});
    }
    return options;
}

Result TSPSolver::buildRegretPath(int start_index, bool weighted) const {
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
            candidate.best = *std::min_element(options.begin(), options.end(), [](const auto& lhs, const auto& rhs) {
                return lhs.delta < rhs.delta || (lhs.delta == rhs.delta && lhs.position < rhs.position);
            });
            auto second = std::numeric_limits<int>::max();
            for (const auto& option : options) {
                if (option.position != candidate.best.position) {
                    second = std::min(second, option.delta);
                }
            }
            if (second == std::numeric_limits<int>::max()) {
                second = candidate.best.delta;
            }
            candidate.regret = static_cast<double>(second - candidate.best.delta);
            candidate.score = candidate.regret - static_cast<double>(candidate.best.delta);
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
    return makeResult(path);
}

Result TSPSolver::buildRegretCycle(int start_index, bool weighted) const {
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> cycle{start_index};
    std::vector<char> used(n, 0);
    used[start_index] = 1;
    if (target_count_ == 1) {
        return makeResult(cycle);
    }

    int second = -1;
    int best_delta = std::numeric_limits<int>::max();
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
            candidate.best = *std::min_element(options.begin(), options.end(), [](const auto& lhs, const auto& rhs) {
                return lhs.delta < rhs.delta || (lhs.delta == rhs.delta && lhs.position < rhs.position);
            });
            auto second_delta = std::numeric_limits<int>::max();
            for (const auto& option : options) {
                if (option.position != candidate.best.position) {
                    second_delta = std::min(second_delta, option.delta);
                }
            }
            if (second_delta == std::numeric_limits<int>::max()) {
                second_delta = candidate.best.delta;
            }
            candidate.regret = static_cast<double>(second_delta - candidate.best.delta);
            candidate.score = candidate.regret - static_cast<double>(candidate.best.delta);
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
    return makeResult(cycle);
}

Result TSPSolver::bestGreedyStartingSolution(int start_index) const {
    const std::vector<Result> candidates = {
        buildRegretPath(start_index, false),
        buildRegretCycle(start_index, false),
        buildRegretPath(start_index, true),
        buildRegretCycle(start_index, true),
    };
    return *std::min_element(candidates.begin(), candidates.end(), [](const Result& lhs, const Result& rhs) {
        return lhs.total_cost < rhs.total_cost;
    });
}

std::vector<TSPSolver::Move> TSPSolver::neighborhood(const std::vector<int>& route,
                                                     IntraNeighborhood intra) const {
    const int k = static_cast<int>(route.size());
    std::vector<Move> moves;
    if (intra == IntraNeighborhood::NodeExchange) {
        for (int first = 0; first < k; ++first) {
            for (int second = first + 1; second < k; ++second) {
                moves.push_back({MoveType::IntraNodeExchange, first, second});
            }
        }
    } else {
        for (int first = 0; first < k; ++first) {
            for (int second = first + 2; second < k; ++second) {
                if (first == 0 && second == k - 1) {
                    continue;
                }
                moves.push_back({MoveType::TwoOpt, first, second});
            }
        }
    }

    std::vector<char> selected(nodes_.size(), 0);
    for (int node : route) {
        selected[node] = 1;
    }
    for (int position = 0; position < k; ++position) {
        for (int node = 0; node < static_cast<int>(nodes_.size()); ++node) {
            if (!selected[node]) {
                moves.push_back({MoveType::InterNodeExchange, position, node});
            }
        }
    }
    return moves;
}

int TSPSolver::moveDelta(const std::vector<int>& route, const Move& move) const {
    const int k = static_cast<int>(route.size());
    const auto previous = [k](int position) { return (position + k - 1) % k; };
    const auto next = [k](int position) { return (position + 1) % k; };

    if (move.type == MoveType::InterNodeExchange) {
        const int position = move.first;
        const int old_node = route[position];
        const int new_node = move.second;
        const int before = route[previous(position)];
        const int after = route[next(position)];
        const int old_edges = distance_matrix_[before][old_node] + distance_matrix_[old_node][after];
        const int new_edges = distance_matrix_[before][new_node] + distance_matrix_[new_node][after];
        return new_edges - old_edges + nodes_[new_node].cost - nodes_[old_node].cost;
    }

    if (move.type == MoveType::TwoOpt) {
        const int first = move.first;
        const int second = move.second;
        const int before = route[previous(first)];
        const int after = route[next(second)];
        const int old_edges = distance_matrix_[before][route[first]] + distance_matrix_[route[second]][after];
        const int new_edges = distance_matrix_[before][route[second]] + distance_matrix_[route[first]][after];
        return new_edges - old_edges;
    }

    const int first = move.first;
    const int second = move.second;
    std::set<int> affected_edges = {previous(first), first, previous(second), second};
    const auto node_after_swap = [&](int position) {
        if (position == first) {
            return route[second];
        }
        if (position == second) {
            return route[first];
        }
        return route[position];
    };
    int delta = 0;
    for (int edge : affected_edges) {
        const int old_from = route[edge];
        const int old_to = route[next(edge)];
        const int new_from = node_after_swap(edge);
        const int new_to = node_after_swap(next(edge));
        delta += distance_matrix_[new_from][new_to] - distance_matrix_[old_from][old_to];
    }
    return delta;
}

void TSPSolver::applyMove(std::vector<int>& route, const Move& move) const {
    if (move.type == MoveType::InterNodeExchange) {
        route[move.first] = move.second;
    } else if (move.type == MoveType::TwoOpt) {
        std::reverse(route.begin() + move.first, route.begin() + move.second + 1);
    } else {
        std::swap(route[move.first], route[move.second]);
    }
}

Result TSPSolver::localSearch(const Result& initial, SearchStrategy strategy, IntraNeighborhood intra,
                              std::mt19937& rng) const {
    if (initial.route.size() != static_cast<std::size_t>(target_count_ + 1) ||
        initial.route.front() != initial.route.back()) {
        throw std::invalid_argument("local search received an invalid closed route");
    }

    std::vector<int> route(initial.route.begin(), initial.route.end() - 1);
    int current_cost = objective(route);
    while (true) {
        auto moves = neighborhood(route, intra);
        Move selected{};
        int selected_delta = 0;
        bool found = false;

        if (strategy == SearchStrategy::Steepest) {
            for (const auto& move : moves) {
                const int delta = moveDelta(route, move);
                if (delta < selected_delta) {
                    selected = move;
                    selected_delta = delta;
                    found = true;
                }
            }
        } else {
            std::shuffle(moves.begin(), moves.end(), rng);
            for (const auto& move : moves) {
                const int delta = moveDelta(route, move);
                if (delta < 0) {
                    selected = move;
                    selected_delta = delta;
                    found = true;
                    break;
                }
            }
        }

        if (!found) {
            break;
        }
        applyMove(route, selected);
        current_cost += selected_delta;
    }

    Result result = makeResult(route);
    if (result.total_cost != current_cost) {
        throw std::logic_error("local-search delta accounting disagrees with objective recomputation");
    }
    return result;
}
