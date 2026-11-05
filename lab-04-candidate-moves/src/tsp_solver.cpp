#include "tsp_solver.hpp"

#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <utility>

TSPSolver::TSPSolver(const std::vector<std::vector<int>>& distance_matrix, const std::vector<Node>& nodes,
                     int candidate_count, CandidateRanking candidate_ranking)
    : distance_matrix_(distance_matrix),
      nodes_(nodes),
      candidate_ranking_(candidate_ranking),
      target_count_(std::max(1, static_cast<int>(std::ceil(nodes.size() / 2.0)))) {
    if (nodes_.empty() || distance_matrix_.size() != nodes_.size()) {
        throw std::invalid_argument("invalid instance or distance matrix");
    }
    for (const auto& row : distance_matrix_) {
        if (row.size() != nodes_.size()) {
            throw std::invalid_argument("distance matrix must be square");
        }
    }
    if (candidate_count <= 0 || candidate_count >= static_cast<int>(nodes_.size())) {
        throw std::invalid_argument("candidate count must be positive and smaller than the instance size");
    }
    buildCandidateLists(candidate_count);
}

int TSPSolver::objective(const std::vector<int>& route) const {
    if (route.empty()) {
        return 0;
    }

    int total = 0;
    for (std::size_t index = 0; index < route.size(); ++index) {
        total += nodes_[route[index]].cost;
        total += distance_matrix_[route[index]][route[(index + 1) % route.size()]];
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
    std::vector<int> route(nodes_.size());
    std::iota(route.begin(), route.end(), 0);
    std::shuffle(route.begin(), route.end(), rng);
    route.resize(static_cast<std::size_t>(target_count_));
    return makeResult(route);
}

void TSPSolver::buildCandidateLists(int candidate_count) {
    const int n = static_cast<int>(nodes_.size());
    std::vector<std::vector<char>> intra_edges(static_cast<std::size_t>(n), std::vector<char>(n, 0));
    std::vector<std::vector<char>> inter_edges(static_cast<std::size_t>(n), std::vector<char>(n, 0));

    for (int vertex = 0; vertex < n; ++vertex) {
        std::vector<std::pair<int, int>> intra_ranking;
        std::vector<std::pair<int, int>> inter_ranking;
        intra_ranking.reserve(static_cast<std::size_t>(n - 1));
        inter_ranking.reserve(static_cast<std::size_t>(n - 1));

        for (int other = 0; other < n; ++other) {
            if (other == vertex) {
                continue;
            }
            const int node_costs = nodes_[vertex].cost + nodes_[other].cost;
            const int intra_score = candidate_ranking_ == CandidateRanking::DistancePlusNodeCostsForAll
                                        ? distance_matrix_[vertex][other] + node_costs
                                        : distance_matrix_[vertex][other];
            intra_ranking.emplace_back(intra_score, other);
            const int inter_score = distance_matrix_[vertex][other] + node_costs;
            inter_ranking.emplace_back(inter_score, other);
        }

        auto ranking_order = [](const auto& lhs, const auto& rhs) {
            if (lhs.first != rhs.first) {
                return lhs.first < rhs.first;
            }
            return lhs.second < rhs.second;
        };
        std::sort(intra_ranking.begin(), intra_ranking.end(), ranking_order);
        std::sort(inter_ranking.begin(), inter_ranking.end(), ranking_order);

        const int limit = std::min(candidate_count, n - 1);
        for (int index = 0; index < limit; ++index) {
            const int intra_neighbor = intra_ranking[static_cast<std::size_t>(index)].second;
            intra_edges[vertex][intra_neighbor] = 1;
            intra_edges[intra_neighbor][vertex] = 1;

            const int inter_neighbor = inter_ranking[static_cast<std::size_t>(index)].second;
            inter_edges[vertex][inter_neighbor] = 1;
            inter_edges[inter_neighbor][vertex] = 1;
        }
    }

    intra_candidates_.assign(static_cast<std::size_t>(n), {});
    inter_candidates_.assign(static_cast<std::size_t>(n), {});
    for (int vertex = 0; vertex < n; ++vertex) {
        for (int other = 0; other < n; ++other) {
            if (intra_edges[vertex][other]) {
                intra_candidates_[vertex].push_back(other);
            }
            if (inter_edges[vertex][other]) {
                inter_candidates_[vertex].push_back(other);
            }
        }
    }
}

std::vector<TSPSolver::Move> TSPSolver::fullNeighborhood(const std::vector<int>& route) const {
    const int k = static_cast<int>(route.size());
    std::vector<Move> moves;
    moves.reserve(static_cast<std::size_t>(k * k + k * (static_cast<int>(nodes_.size()) - k)));

    for (int first = 0; first < k; ++first) {
        for (int second = first + 2; second < k; ++second) {
            if (first == 0 && second == k - 1) {
                continue;
            }
            moves.push_back({MoveType::TwoOpt, first, second});
        }
    }

    std::vector<char> selected(nodes_.size(), 0);
    for (int node : route) {
        selected[static_cast<std::size_t>(node)] = 1;
    }
    for (int position = 0; position < k; ++position) {
        for (int node = 0; node < static_cast<int>(nodes_.size()); ++node) {
            if (!selected[static_cast<std::size_t>(node)]) {
                moves.push_back({MoveType::InterNodeExchange, position, node});
            }
        }
    }
    return moves;
}

std::vector<TSPSolver::Move> TSPSolver::candidateNeighborhood(const std::vector<int>& route) const {
    const int n = static_cast<int>(nodes_.size());
    const int k = static_cast<int>(route.size());
    const auto previous = [k](int position) { return (position + k - 1) % k; };
    const auto next = [k](int position) { return (position + 1) % k; };

    std::vector<char> selected(static_cast<std::size_t>(n), 0);
    std::vector<int> position_of(static_cast<std::size_t>(n), -1);
    for (int position = 0; position < k; ++position) {
        selected[static_cast<std::size_t>(route[position])] = 1;
        position_of[static_cast<std::size_t>(route[position])] = position;
    }

    std::vector<Move> moves;
    std::vector<char> seen_two_opt(static_cast<std::size_t>(k * k), 0);
    auto add_two_opt = [&](int first, int second) {
        if (first < 0 || second < 0 || first >= second || second >= k || second < first + 2 ||
            (first == 0 && second == k - 1)) {
            return;
        }
        const std::size_t marker = static_cast<std::size_t>(first * k + second);
        if (!seen_two_opt[marker]) {
            seen_two_opt[marker] = 1;
            moves.push_back({MoveType::TwoOpt, first, second});
        }
    };

    // A 2-opt move introduces (prev(first), route[second]) or
    // (route[first], next(second)). Generate from candidate lists directly.
    for (int first = 0; first < k; ++first) {
        const int before = route[previous(first)];
        for (int candidate : intra_candidates_[static_cast<std::size_t>(before)]) {
            if (!selected[static_cast<std::size_t>(candidate)]) {
                continue;
            }
            const int second = position_of[static_cast<std::size_t>(candidate)];
            if (second > first + 1) {
                add_two_opt(first, second);
            }
        }

        const int first_node = route[first];
        for (int candidate : intra_candidates_[static_cast<std::size_t>(first_node)]) {
            if (!selected[static_cast<std::size_t>(candidate)]) {
                continue;
            }
            const int candidate_position = position_of[static_cast<std::size_t>(candidate)];
            const int second = previous(candidate_position);
            if (second > first + 1) {
                add_two_opt(first, second);
            }
        }
    }

    for (int position = 0; position < k; ++position) {
        const int before = route[previous(position)];
        const int after = route[next(position)];
        std::vector<char> seen_replacement(static_cast<std::size_t>(n), 0);

        auto add_replacements = [&](int endpoint) {
            for (int candidate : inter_candidates_[static_cast<std::size_t>(endpoint)]) {
                if (!selected[static_cast<std::size_t>(candidate)] &&
                    !seen_replacement[static_cast<std::size_t>(candidate)]) {
                    seen_replacement[static_cast<std::size_t>(candidate)] = 1;
                    moves.push_back({MoveType::InterNodeExchange, position, candidate});
                }
            }
        };
        add_replacements(before);
        add_replacements(after);
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

    const int first = move.first;
    const int second = move.second;
    const int before = route[previous(first)];
    const int after = route[next(second)];
    const int old_edges = distance_matrix_[before][route[first]] + distance_matrix_[route[second]][after];
    const int new_edges = distance_matrix_[before][route[second]] + distance_matrix_[route[first]][after];
    return new_edges - old_edges;
}

void TSPSolver::applyMove(std::vector<int>& route, const Move& move) const {
    if (move.type == MoveType::TwoOpt) {
        std::reverse(route.begin() + move.first, route.begin() + move.second + 1);
    } else {
        route[move.first] = move.second;
    }
}

Result TSPSolver::steepestLocalSearch(const Result& initial, bool use_candidate_moves) const {
    if (initial.route.size() != static_cast<std::size_t>(target_count_ + 1) ||
        initial.route.front() != initial.route.back()) {
        throw std::invalid_argument("local search received an invalid closed route");
    }

    std::vector<int> route(initial.route.begin(), initial.route.end() - 1);
    int current_cost = objective(route);
    while (true) {
        const std::vector<Move> moves = use_candidate_moves
                                           ? candidateNeighborhood(route)
                                           : fullNeighborhood(route);
        Move best_move{};
        int best_delta = 0;
        bool found = false;
        for (const auto& move : moves) {
            const int delta = moveDelta(route, move);
            if (delta < best_delta) {
                best_delta = delta;
                best_move = move;
                found = true;
            }
        }

        if (!found) {
            break;
        }
        applyMove(route, best_move);
        current_cost += best_delta;
    }

    Result result = makeResult(route);
    if (result.total_cost != current_cost) {
        throw std::logic_error("local-search delta accounting disagrees with objective recomputation");
    }
    return result;
}
