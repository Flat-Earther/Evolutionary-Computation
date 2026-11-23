#include "tsp_solver.hpp"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <utility>

#if defined(_MSC_VER) && !defined(__clang__)
#include <intrin.h>
#endif

namespace {

// Added to the cost of selected nodes so that the exchange scan of the full neighbourhood
// can run over all nodes without a branch (selected nodes can then never be the minimum).
constexpr int kSelectedPenalty = 1 << 29;
// Bound on distances and node costs that keeps sums like d + d + penalty inside int.
constexpr int kMaxInputValue = 1 << 26;

inline int lowestSetBit(std::uint64_t word) {
#if defined(_MSC_VER) && !defined(__clang__)
    unsigned long index = 0;
    _BitScanForward64(&index, word);
    return static_cast<int>(index);
#else
    return __builtin_ctzll(word);
#endif
}

inline void flipBit(std::uint64_t* words, int bit) {
    words[bit >> 6] ^= std::uint64_t{1} << (bit & 63);
}

// Calls visit(entry) for every entry of list `owner` whose bit is set, in list order.
template <typename Visit>
inline void forEachMarked(const int* offsets, const int* words, const std::uint64_t* marks, int owner,
                          Visit&& visit) {
    int entry_base = offsets[owner];
    for (int word = words[owner], end = words[owner + 1]; word < end; ++word, entry_base += 64) {
        for (std::uint64_t bits = marks[word]; bits != 0; bits &= bits - 1) {
            visit(entry_base + lowestSetBit(bits));
        }
    }
}

// Same, but stops as soon as visit(entry) returns false.
template <typename Visit>
inline void forEachMarkedWhile(const int* offsets, const int* words, const std::uint64_t* marks, int owner,
                               Visit&& visit) {
    int entry_base = offsets[owner];
    for (int word = words[owner], end = words[owner + 1]; word < end; ++word, entry_base += 64) {
        for (std::uint64_t bits = marks[word]; bits != 0; bits &= bits - 1) {
            if (!visit(entry_base + lowestSetBit(bits))) {
                return;
            }
        }
    }
}

}  // namespace

// State of one local-search run.
//
// The route is stored with two sentinel copies on each side, so that neighbours of any
// position are read without modulo arithmetic:
//     route_[-2], route_[-1] | route_[0] ... route_[k-1] | route_[k], route_[k+1]
// with route_[-1] == route_[k-1], route_[k] == route_[0], and so on. edge_[i] caches the
// length of the route edge (route_[i], route_[i+1]) and has the same sentinels. pos_ maps
// a node to its route position, or -1 when the node is not selected.
//
// For the candidate neighbourhood, intra_selected_ marks the entries of the 2-opt lists
// whose node is selected and inter_unselected_ marks the entries of the exchange lists
// whose node is not selected, so scans skip entries that cannot form a move.
// intra_pending_ is per-scan scratch space (see bestCandidateMove).
class TSPSolver::Search {
public:
    Search(const TSPSolver& solver, const std::vector<int>& closed_route, bool full_neighborhood);

    int cost() const;
    Move bestFullMove() const;
    Move bestCandidateMove();
    void apply(const Move& move);
    std::vector<int> route() const { return {route_, route_ + k_}; }

private:
    const int* distancesFrom(int node) const { return distances_ + static_cast<std::ptrdiff_t>(node) * n_; }
    void refreshRouteSentinels();
    void refreshEdgeSentinels();
    void flipSelection(int node);

    const TSPSolver& solver_;
    const int* distances_;
    const int* costs_;
    int n_;
    int k_;
    bool full_neighborhood_;
    std::vector<int> route_storage_;
    std::vector<int> edge_storage_;
    int* route_;
    int* edge_;
    std::vector<int> pos_;
    std::vector<int> exchange_cost_;  // full neighbourhood only: cost(v), or kSelectedPenalty if selected
    std::vector<std::uint64_t> intra_selected_;
    std::vector<std::uint64_t> intra_pending_;
    std::vector<std::uint64_t> inter_unselected_;
};

TSPSolver::Search::Search(const TSPSolver& solver, const std::vector<int>& closed_route, bool full_neighborhood)
    : solver_(solver),
      distances_(solver.distances_.row(0)),
      costs_(solver.costs_.data()),
      n_(solver.node_count_),
      k_(solver.target_count_),
      full_neighborhood_(full_neighborhood),
      route_storage_(static_cast<std::size_t>(k_) + 4),
      edge_storage_(static_cast<std::size_t>(k_) + 4),
      route_(route_storage_.data() + 2),
      edge_(edge_storage_.data() + 2),
      pos_(static_cast<std::size_t>(n_), -1) {
    for (int position = 0; position < k_; ++position) {
        const int node = closed_route[static_cast<std::size_t>(position)];
        if (node < 0 || node >= n_ || pos_[static_cast<std::size_t>(node)] != -1) {
            throw std::invalid_argument("local search received a route with invalid or repeated nodes");
        }
        route_[position] = node;
        pos_[static_cast<std::size_t>(node)] = position;
    }
    refreshRouteSentinels();
    for (int position = 0; position < k_; ++position) {
        edge_[position] = distancesFrom(route_[position])[route_[position + 1]];
    }
    refreshEdgeSentinels();

    if (full_neighborhood_) {
        exchange_cost_.assign(costs_, costs_ + n_);
        for (int position = 0; position < k_; ++position) {
            exchange_cost_[static_cast<std::size_t>(route_[position])] = kSelectedPenalty;
        }
        return;
    }

    // Start from "nothing selected" (no intra entry marked, every inter entry marked)
    // and flip the selected nodes in.
    const CandidateLists& inter = solver_.inter_;
    intra_selected_.assign(static_cast<std::size_t>(solver_.intra_.words.back()), 0);
    intra_pending_.assign(intra_selected_.size(), 0);
    inter_unselected_.assign(static_cast<std::size_t>(inter.words.back()), 0);
    for (int node = 0; node < n_; ++node) {
        const int size = inter.offsets[static_cast<std::size_t>(node) + 1] - inter.offsets[static_cast<std::size_t>(node)];
        const int first_bit = inter.words[static_cast<std::size_t>(node)] * 64;
        for (int bit = first_bit; bit < first_bit + size; ++bit) {
            flipBit(inter_unselected_.data(), bit);
        }
    }
    for (int position = 0; position < k_; ++position) {
        flipSelection(route_[position]);
    }
}

void TSPSolver::Search::refreshRouteSentinels() {
    route_[-1] = route_[k_ - 1];
    route_[-2] = route_[(2 * k_ - 2) % k_];
    route_[k_] = route_[0];
    route_[k_ + 1] = route_[1 % k_];
}

void TSPSolver::Search::refreshEdgeSentinels() {
    edge_[-1] = edge_[k_ - 1];
    edge_[-2] = edge_[(2 * k_ - 2) % k_];
    edge_[k_] = edge_[0];
    edge_[k_ + 1] = edge_[1 % k_];
}

// Toggles the selection status of `node` in the bitmasks of every list that contains it.
void TSPSolver::Search::flipSelection(int node) {
    const CandidateLists& intra = solver_.intra_;
    for (int entry = intra.offsets[static_cast<std::size_t>(node)]; entry < intra.offsets[static_cast<std::size_t>(node) + 1];
         ++entry) {
        flipBit(intra_selected_.data(), intra.mirror_bit[static_cast<std::size_t>(entry)]);
    }
    const CandidateLists& inter = solver_.inter_;
    for (int entry = inter.offsets[static_cast<std::size_t>(node)]; entry < inter.offsets[static_cast<std::size_t>(node) + 1];
         ++entry) {
        flipBit(inter_unselected_.data(), inter.mirror_bit[static_cast<std::size_t>(entry)]);
    }
}

int TSPSolver::Search::cost() const {
    int total = 0;
    for (int position = 0; position < k_; ++position) {
        total += edge_[position] + costs_[route_[position]];
    }
    return total;
}

// Complete neighbourhood, evaluated in the reference order: all 2-opt moves by (first,
// second), then all exchanges by (position, node). Only a strictly better move replaces
// the current best, so the result is the first move with the lowest delta. Every row is
// reduced to its minimum without branches; the position of the minimum is looked up only
// when it beats the best move so far, which happens a few times per neighbourhood.
TSPSolver::Move TSPSolver::Search::bestFullMove() const {
    const int k = k_;
    const int n = n_;
    const int* route = route_;
    const int* edge = edge_;
    const int* exchange_cost = exchange_cost_.data();
    Move best;

    // 2-opt (first, second): reverse route[first..second] for first + 1 <= second <= k - 1,
    // except (0, k - 1), which would reverse the whole cycle. Removes the edges
    // (a, b) = (route[first-1], route[first]) and (c, d) = (route[second], route[second+1])
    // and adds (a, c) and (b, d). second == first + 1 swaps two neighbouring nodes; the
    // edge (b, c) between them stays, with the same length because the matrix is symmetric.
    for (int first = 0; first < k; ++first) {
        const int* from_a = distancesFrom(route[first - 1]);
        const int* from_b = distancesFrom(route[first]);
        const int removed_ab = edge[first - 1];
        const int last = first == 0 ? k - 2 : k - 1;
        const auto partial = [&](int second) {
            return from_a[route[second]] + from_b[route[second + 1]] - edge[second];
        };
        // Four independent minima keep the reduction from being one long dependency chain.
        int lowest0 = INT_MAX;
        int lowest1 = INT_MAX;
        int lowest2 = INT_MAX;
        int lowest3 = INT_MAX;
        int second = first + 1;
        for (; second + 3 <= last; second += 4) {
            lowest0 = std::min(lowest0, partial(second));
            lowest1 = std::min(lowest1, partial(second + 1));
            lowest2 = std::min(lowest2, partial(second + 2));
            lowest3 = std::min(lowest3, partial(second + 3));
        }
        for (; second <= last; ++second) {
            lowest0 = std::min(lowest0, partial(second));
        }
        const int lowest = std::min(std::min(lowest0, lowest1), std::min(lowest2, lowest3));
        if (lowest - removed_ab < best.delta) {
            second = first + 1;
            while (partial(second) != lowest) {
                ++second;
            }
            best = {lowest - removed_ab, MoveType::TwoOpt, first, second};
        }
    }

    // Exchange: replace route[position] with an unselected node. The minimum over all
    // nodes is a branch-free, vectorisable scan; the arg-min is searched for only when it
    // beats the best move found so far.
    for (int position = 0; position < k; ++position) {
        const int* from_before = distancesFrom(route[position - 1]);
        const int* from_after = distancesFrom(route[position + 1]);
        const int removed = edge[position - 1] + edge[position] + costs_[route[position]];
        int lowest = INT_MAX;
        for (int node = 0; node < n; ++node) {
            lowest = std::min(lowest, from_before[node] + from_after[node] + exchange_cost[node]);
        }
        if (lowest - removed < best.delta) {
            int node = 0;
            while (from_before[node] + from_after[node] + exchange_cost[node] != lowest) {
                ++node;
            }
            best = {lowest - removed, MoveType::Exchange, position, node};
        }
    }
    return best;
}

// Candidate neighbourhood: only moves that introduce at least one candidate edge, generated
// directly from the candidate lists. Every selected node u = route[q] is visited once; its
// 2-opt list yields the selected candidates v and its exchange list the unselected ones.
// A candidate edge (u, v) is introduced by two moves of each kind, and both are evaluated:
//   2-opt, v = route[j]:  reverse route[q .. j-1]   adds (u, v) and (route[q-1], route[j-1])
//                         reverse route[q+1 .. j]   adds (u, v) and (route[q+1], route[j+1])
//   exchange:             v replaces route[q+1]     adds (u, v) and (v, route[q+2])
//                         v replaces route[q-1]     adds (route[q-2], v) and (v, u)
//
// Ties are resolved exactly like in the reference implementation, which scanned 2-opt
// groups B(f), C(f) for f = 0..k-1 (the lists of route[f-1] and route[f]) and then exchange
// groups for every position (the list of the node before it, then of the node after it),
// each list in node order, keeping the first move with the lowest delta. Every move here
// carries its rank in that order, and the best move is the lowest (delta, rank) pair:
//   rank = group * n + index of v among u's candidates ordered by node index,
//   group: B(f) = 2f, C(f) = 2f + 1, exchange at p via node before = 2k + 2p, via node after = 2k + 2p + 1.
// The scan order is therefore free; it is chosen for speed. Hot loops compare against bounds
// derived from the best delta and enter the rare branch only for moves at least as good as
// the best one so far.
//
// A pair of selected nodes appears in both of their 2-opt lists, but only the node with the
// smaller position can form a valid move with the other one (apart from the wrap-around
// moves handled below). intra_pending_ starts as a copy of intra_selected_; when an owner is
// visited, its own bit is cleared in the lists of its candidates, so owners visited later no
// longer see it.
TSPSolver::Move TSPSolver::Search::bestCandidateMove() {
    const int k = k_;
    const std::int64_t n = n_;
    const int* route = route_;
    const int* edge = edge_;
    const int* pos = pos_.data();
    const int* costs = costs_;
    const CandidateLists& intra = solver_.intra_;
    const CandidateLists& inter = solver_.inter_;
    const int* intra_offsets = intra.offsets.data();
    const int* intra_words = intra.words.data();
    const Candidate* intra_entries = intra.entries.data();
    const int* intra_mirror_bit = intra.mirror_bit.data();
    const std::uint64_t* intra_selected = intra_selected_.data();
    std::copy(intra_selected_.begin(), intra_selected_.end(), intra_pending_.begin());
    std::uint64_t* intra_pending = intra_pending_.data();
    const int* inter_offsets = inter.offsets.data();
    const int* inter_words = inter.words.data();
    const Candidate* inter_entries = inter.entries.data();
    const int* inter_rank = inter.rank.data();
    const std::uint64_t* inter_unselected = inter_unselected_.data();

    Move best;
    std::int64_t best_rank = -1;  // a move with delta 0 never replaces "no move"
    const auto consider = [&](int delta, std::int64_t rank, MoveType type, int first, int second) {
        if (delta < best.delta || (delta == best.delta && rank < best_rank)) {
            best = {delta, type, first, second};
            best_rank = rank;
        }
    };

    for (int q = 0; q < k; ++q) {
        const int owner = route[q];

        // 2-opt: C(q) reverses route[q .. j-1] (j == 0 wraps to k - 1), B(q+1) reverses
        // route[q+1 .. j]; a move needs second > first. For j >= 1 both therefore need
        // j - 1 >= q + 1; for j == 0 only C(q) exists and needs k - 1 >= q + 1. With
        // q <= k - 2 both tests are the single comparison of j - 1 with q + 1: signed for
        // B(q+1), unsigned for C(q) (0 - 1 wraps to the maximum). Owner k - 1 only serves
        // B(0), whose candidates sit at small positions, so it scans the full selection mask.
        // Owner 0 does not hide itself, because later owners need it for their wrap-around
        // C moves.
        if (q <= k - 2) {
            const int* from_prev = distancesFrom(route[q - 1]);
            const int* from_next = distancesFrom(route[q + 1]);
            const int removed_c = edge[q - 1];  // (route[q-1], u)
            const int removed_b = edge[q];      // (u, route[q+1])
            const int min_gap = q + 1;
            int bound_c = best.delta + removed_c;
            int bound_b = best.delta + removed_b;
            const std::uint64_t hide = q == 0 ? 0 : ~std::uint64_t{0};
            forEachMarked(intra_offsets, intra_words, intra_pending, owner, [&](int entry) {
                const int mirror = intra_mirror_bit[entry];
                intra_pending[mirror >> 6] &= ~((std::uint64_t{1} << (mirror & 63)) & hide);
                const Candidate candidate = intra_entries[entry];
                const int j = pos[candidate.node];
                const int partial_c = from_prev[route[j - 1]] + candidate.weight - edge[j - 1];
                const int partial_b = candidate.weight + from_next[route[j + 1]] - edge[j];
                const bool forward_c = static_cast<unsigned>(j - 1) >= static_cast<unsigned>(min_gap);
                const bool forward_b = j - 1 >= min_gap;
                const bool hit_c = forward_c & (partial_c <= bound_c);
                const bool hit_b = forward_b & (partial_b <= bound_b);
                if (hit_c | hit_b) {
                    const std::int64_t index = entry - intra_offsets[owner];
                    if (hit_c) {
                        consider(partial_c - removed_c, (2 * static_cast<std::int64_t>(q) + 1) * n + index,
                                 MoveType::TwoOpt, q, j == 0 ? k - 1 : j - 1);
                    }
                    if (hit_b) {
                        consider(partial_b - removed_b, (2 * static_cast<std::int64_t>(q) + 2) * n + index,
                                 MoveType::TwoOpt, q + 1, j);
                    }
                    bound_c = best.delta + removed_c;
                    bound_b = best.delta + removed_b;
                }
            });
        } else {
            // B(0): reverse route[0 .. j] for j >= 1, adds (u, v) and (route[0], route[j+1]).
            const int* from_first = distancesFrom(route[0]);
            const int removed_b = edge[k - 1];
            int bound_b = best.delta + removed_b;
            forEachMarked(intra_offsets, intra_words, intra_selected, owner, [&](int entry) {
                const Candidate candidate = intra_entries[entry];
                const int j = pos[candidate.node];
                const int partial_b = candidate.weight + from_first[route[j + 1]] - edge[j];
                if ((j >= 1) & (partial_b <= bound_b)) {
                    consider(partial_b - removed_b, entry - intra_offsets[owner], MoveType::TwoOpt, 0, j);
                    bound_b = best.delta + removed_b;
                }
            });
        }

        // Exchange: v replaces route[q+1] (u is the node before it) or route[q-1] (u is after
        // it). The added cost is weight + d(., v) >= weight, and the list is sorted by weight,
        // so the scan stops at the first candidate whose weight exceeds both bounds: no later
        // candidate can match or beat the best move.
        {
            const int next_position = q + 1 == k ? 0 : q + 1;
            const int prev_position = q == 0 ? k - 1 : q - 1;
            const int removed_next = edge[q] + edge[q + 1] + costs[route[q + 1]];
            const int removed_prev = edge[q - 2] + edge[q - 1] + costs[route[q - 1]];
            const int* from_after_next = distancesFrom(route[q + 2]);
            const int* from_before_prev = distancesFrom(route[q - 2]);
            const std::int64_t group_next = 2 * static_cast<std::int64_t>(k) + 2 * static_cast<std::int64_t>(next_position);
            const std::int64_t group_prev = 2 * static_cast<std::int64_t>(k) + 2 * static_cast<std::int64_t>(prev_position) + 1;
            int bound_next = best.delta + removed_next;
            int bound_prev = best.delta + removed_prev;
            int bound_any = std::max(bound_next, bound_prev);
            forEachMarkedWhile(inter_offsets, inter_words, inter_unselected, owner, [&](int entry) {
                const Candidate candidate = inter_entries[entry];  // weight = d(u, v) + cost(v)
                if (candidate.weight > bound_any) {
                    return false;
                }
                const int added_next = candidate.weight + from_after_next[candidate.node];
                const int added_prev = candidate.weight + from_before_prev[candidate.node];
                const bool hit_next = added_next <= bound_next;
                const bool hit_prev = added_prev <= bound_prev;
                if (hit_next | hit_prev) {
                    const std::int64_t index = inter_rank[entry];
                    if (hit_next) {
                        consider(added_next - removed_next, group_next * n + index, MoveType::Exchange, next_position,
                                 candidate.node);
                    }
                    if (hit_prev) {
                        consider(added_prev - removed_prev, group_prev * n + index, MoveType::Exchange, prev_position,
                                 candidate.node);
                    }
                    bound_next = best.delta + removed_next;
                    bound_prev = best.delta + removed_prev;
                    bound_any = std::max(bound_next, bound_prev);
                }
                return true;
            });
        }
    }
    return best;
}

void TSPSolver::Search::apply(const Move& move) {
    if (move.type == MoveType::TwoOpt) {
        const int first = move.first;
        const int second = move.second;
        std::reverse(route_ + first, route_ + second + 1);
        for (int position = first; position <= second; ++position) {
            pos_[static_cast<std::size_t>(route_[position])] = position;
        }
        // Edges strictly inside the segment keep their lengths (the matrix is symmetric),
        // only their order is reversed. The two boundary edges are new.
        std::reverse(edge_ + first, edge_ + second);
        refreshRouteSentinels();
        edge_[first == 0 ? k_ - 1 : first - 1] = distancesFrom(route_[first - 1])[route_[first]];
        edge_[second] = distancesFrom(route_[second])[route_[second + 1]];
    } else {
        const int position = move.first;
        const int entering = move.second;
        const int leaving = route_[position];
        route_[position] = entering;
        pos_[static_cast<std::size_t>(leaving)] = -1;
        pos_[static_cast<std::size_t>(entering)] = position;
        if (full_neighborhood_) {
            exchange_cost_[static_cast<std::size_t>(leaving)] = costs_[leaving];
            exchange_cost_[static_cast<std::size_t>(entering)] = kSelectedPenalty;
        } else {
            flipSelection(leaving);
            flipSelection(entering);
        }
        refreshRouteSentinels();
        edge_[position == 0 ? k_ - 1 : position - 1] = distancesFrom(route_[position - 1])[entering];
        edge_[position] = distancesFrom(entering)[route_[position + 1]];
    }
    refreshEdgeSentinels();
}

TSPSolver::TSPSolver(const DistanceMatrix& distances, std::vector<int> node_costs, int candidate_count,
                     CandidateDefinition candidate_definition)
    : distances_(distances),
      costs_(std::move(node_costs)),
      node_count_(static_cast<int>(costs_.size())),
      target_count_(std::max(1, static_cast<int>(std::ceil(costs_.size() / 2.0)))) {
    if (costs_.empty() || distances_.size() != node_count_) {
        throw std::invalid_argument("invalid instance or distance matrix");
    }
    if (node_count_ < 3) {
        // A single selected node forms no cycle; the exchange delta would count two edges
        // that do not exist.
        throw std::invalid_argument("instance must contain at least 3 nodes");
    }
    if (candidate_count <= 0 || candidate_count >= node_count_) {
        throw std::invalid_argument("candidate count must be positive and smaller than the instance size");
    }
    for (int from = 0; from < node_count_; ++from) {
        if (costs_[static_cast<std::size_t>(from)] < 0 || costs_[static_cast<std::size_t>(from)] >= kMaxInputValue) {
            throw std::invalid_argument("node costs must be in [0, 2^26)");
        }
        for (int to = 0; to < node_count_; ++to) {
            if (distances_(from, to) < 0 || distances_(from, to) >= kMaxInputValue) {
                throw std::invalid_argument("distances must be in [0, 2^26)");
            }
        }
    }
    const auto started = std::chrono::steady_clock::now();
    buildCandidateLists(candidate_count, candidate_definition);
    candidate_list_ms_ = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
}

int TSPSolver::objective(const std::vector<int>& route) const {
    int total = 0;
    for (std::size_t index = 0; index < route.size(); ++index) {
        total += costs_[static_cast<std::size_t>(route[index])];
        total += distances_(route[index], route[(index + 1) % route.size()]);
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
    std::vector<int> route(static_cast<std::size_t>(node_count_));
    std::iota(route.begin(), route.end(), 0);
    std::shuffle(route.begin(), route.end(), rng);
    route.resize(static_cast<std::size_t>(target_count_));
    return makeResult(route);
}

// For every vertex u the `candidate_count` best-ranked other vertices become its candidates;
// an edge chosen by either endpoint is a candidate edge for both (the lists are symmetric).
// 2-opt and exchange candidates are ranked separately, each by its NearestMetric; ties go
// to the smaller vertex index.
void TSPSolver::buildCandidateLists(int candidate_count, CandidateDefinition candidate_definition) {
    const int n = node_count_;
    const int limit = std::min(candidate_count, n - 1);
    std::vector<char> intra_edge(static_cast<std::size_t>(n) * static_cast<std::size_t>(n), 0);
    std::vector<char> inter_edge(intra_edge.size(), 0);
    // key = score * 2^32 + vertex: one integer comparison orders by score, then by index.
    std::vector<std::uint64_t> keys(static_cast<std::size_t>(n - 1));

    const auto mark_nearest = [&](NearestMetric metric, int vertex, std::vector<char>& is_candidate) {
        const int* from = distances_.row(vertex);
        const int* cost = costs_.data();
        std::size_t count = 0;
        for (int other = 0; other < n; ++other) {
            if (other == vertex) {
                continue;
            }
            const int score = metric == NearestMetric::Distance ? from[other]
                              : metric == NearestMetric::Cost   ? cost[other]
                                                                : from[other] + cost[other];
            keys[count++] = (static_cast<std::uint64_t>(score) << 32) | static_cast<std::uint32_t>(other);
        }
        // Only the set of the `limit` smallest keys matters. A bounded heap (partial_sort) is the
        // cheapest selection for short lists, linear-time selection (nth_element) for long ones.
        if (static_cast<std::size_t>(limit) * 16 <= keys.size()) {
            std::partial_sort(keys.begin(), keys.begin() + limit, keys.end());
        } else {
            std::nth_element(keys.begin(), keys.begin() + (limit - 1), keys.end());
        }
        for (int index = 0; index < limit; ++index) {
            const int neighbor = static_cast<int>(keys[static_cast<std::size_t>(index)] & 0xffffffffu);
            is_candidate[static_cast<std::size_t>(vertex) * n + neighbor] = 1;
            is_candidate[static_cast<std::size_t>(neighbor) * n + vertex] = 1;
        }
    };
    for (int vertex = 0; vertex < n; ++vertex) {
        mark_nearest(candidate_definition.intra, vertex, intra_edge);
        mark_nearest(candidate_definition.inter, vertex, inter_edge);
    }

    intra_ = packCandidateLists(intra_edge, false, false);
    inter_ = packCandidateLists(inter_edge, true, true);
}

TSPSolver::CandidateLists TSPSolver::packCandidateLists(const std::vector<char>& is_candidate, bool add_node_cost,
                                                        bool sort_by_weight) const {
    const int n = node_count_;
    CandidateLists lists;
    lists.offsets.assign(static_cast<std::size_t>(n) + 1, 0);
    lists.words.assign(static_cast<std::size_t>(n) + 1, 0);
    // index_in_list[u * n + v]: position of candidate v in the (final) list of u.
    std::vector<int> index_in_list(static_cast<std::size_t>(n) * static_cast<std::size_t>(n), -1);
    std::vector<int> rank_of(static_cast<std::size_t>(n), 0);  // position among u's candidates by node index
    std::vector<std::uint64_t> row;                             // key = weight * 2^32 + node
    row.reserve(static_cast<std::size_t>(n));
    for (int vertex = 0; vertex < n; ++vertex) {
        const int* from = distances_.row(vertex);
        const char* marked = is_candidate.data() + static_cast<std::size_t>(vertex) * n;
        row.clear();
        for (int other = 0; other < n; ++other) {
            if (marked[other]) {
                const int weight = from[other] + (add_node_cost ? costs_[static_cast<std::size_t>(other)] : 0);
                rank_of[static_cast<std::size_t>(other)] = static_cast<int>(row.size());
                row.push_back((static_cast<std::uint64_t>(weight) << 32) | static_cast<std::uint32_t>(other));
            }
        }
        if (sort_by_weight) {  // by weight, equal weights in node order
            std::sort(row.begin(), row.end());
        }
        for (const std::uint64_t key : row) {
            const int node = static_cast<int>(key & 0xffffffffu);
            index_in_list[static_cast<std::size_t>(vertex) * n + node] =
                static_cast<int>(lists.entries.size()) - lists.offsets[static_cast<std::size_t>(vertex)];
            lists.entries.push_back({node, static_cast<int>(key >> 32)});
            lists.rank.push_back(rank_of[static_cast<std::size_t>(node)]);
        }
        const int size = static_cast<int>(row.size());
        lists.offsets[static_cast<std::size_t>(vertex) + 1] = static_cast<int>(lists.entries.size());
        lists.words[static_cast<std::size_t>(vertex) + 1] = lists.words[static_cast<std::size_t>(vertex)] + (size + 63) / 64;
    }

    lists.mirror_bit.resize(lists.entries.size());
    for (int vertex = 0; vertex < n; ++vertex) {
        for (int entry = lists.offsets[static_cast<std::size_t>(vertex)]; entry < lists.offsets[static_cast<std::size_t>(vertex) + 1];
             ++entry) {
            const int other = lists.entries[static_cast<std::size_t>(entry)].node;
            const int mirror = index_in_list[static_cast<std::size_t>(other) * n + vertex];
            if (mirror < 0) {
                throw std::logic_error("candidate lists must be symmetric");
            }
            lists.mirror_bit[static_cast<std::size_t>(entry)] = lists.words[static_cast<std::size_t>(other)] * 64 + mirror;
        }
    }
    return lists;
}

Result TSPSolver::steepestLocalSearch(const Result& initial, bool use_candidate_moves,
                                     long long* applied_moves) const {
    if (initial.route.size() != static_cast<std::size_t>(target_count_) + 1 ||
        initial.route.front() != initial.route.back()) {
        throw std::invalid_argument("local search received an invalid closed route");
    }

    Search search(*this, initial.route, !use_candidate_moves);
    int current_cost = search.cost();
    while (true) {
        const Move move = use_candidate_moves ? search.bestCandidateMove() : search.bestFullMove();
        if (move.type == MoveType::None) {
            break;
        }
        search.apply(move);
        current_cost += move.delta;
        if (applied_moves) {
            ++*applied_moves;
        }
#ifdef LAB04_DEBUG_CHECKS
        if (objective(search.route()) != current_cost) {
            throw std::logic_error("debug check: tracked cost differs from the objective after a move");
        }
#endif
    }

    Result result = makeResult(search.route());
    if (result.total_cost != current_cost) {
        throw std::logic_error("local-search delta accounting disagrees with objective recomputation");
    }
    return result;
}
