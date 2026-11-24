#include "lm_search.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <utility>

#if defined(_MSC_VER) && !defined(__clang__)
#include <intrin.h>
#endif

#if defined(__SSE2__) || defined(_M_X64) || (defined(_M_IX86_FP) && _M_IX86_FP >= 2)
#define LM_SEARCH_SSE2 1
#include <emmintrin.h>
#endif

namespace {

enum : std::uint16_t { kTwoOpt = 0, kExchange = 1 };

// The three situations of a stored move when LM is browsed.
enum Status : int {
    kInvalid = 0,     // a removed edge (or the node to remove) is gone: drop the move
    kNotNow = 1,      // 2-opt edges exist but with different relative direction: keep, skip
    kApplicable = 2,  // apply the move
};

// A move kept in LM (16 bytes; its delta is not stored, it is given by the LM bucket).
//   2-opt:    removes the edges (a, b) and (c, d), which had the same direction when the move was
//             evaluated, and adds (a, c) and (b, d).
//   exchange: the selected node a, whose neighbours were c and d, is replaced by the not selected
//             node b; adds (c, b) and (b, d).
// The delta depends only on these four nodes, so it stays valid as long as the move applies.
struct StoredMove {
    std::uint16_t a, b, c, d;
    int next;  // next move in the same LM bucket, -1 at the end
    std::uint16_t type;
    std::uint16_t inverted;  // 2-opt evaluated with relatively inverted edges (for statistics only)
};
static_assert(sizeof(StoredMove) == 16, "a stored move should take 16 bytes");

// Entry of an exchange candidate list of node u, sorted by weight = d(u, node) + cost(node).
struct WeightedCandidate {
    int node;
    int weight;
};

// An improving move found by a scan, before it is added to LM.
struct Found {
    int index;  // 2-opt: 2 * position of the other edge, + 1 for the inverted reconnection;
                // exchange: the node to insert, or the position of the node to remove
    int delta;
};

constexpr int kMaxNodes = 65535;  // node ids are stored in 16 bits
constexpr std::size_t kInitialPool = std::size_t{1} << 14;
// Insertion cost of a selected node in the exchange scans: no exchange with it can improve.
constexpr int kBlocked = 1 << 28;

inline int highestSetBit(std::uint64_t word) {
#if defined(_MSC_VER) && !defined(__clang__)
    unsigned long index = 0;
    _BitScanReverse64(&index, word);
    return static_cast<int>(index);
#else
    return 63 - __builtin_clzll(word);
#endif
}

inline int lowestSetBit(std::uint64_t word) {
#if defined(_MSC_VER) && !defined(__clang__)
    unsigned long index = 0;
    _BitScanForward64(&index, word);
    return static_cast<int>(index);
#else
    return __builtin_ctzll(word);
#endif
}

}  // namespace

// Search state, kept between runs so that LM does not have to be allocated again.
// The solution is stored as the route, the length of every route edge (edge_[i] joins route_[i]
// and route_[i + 1]; route_[-1], route_[m], edge_[-1] and edge_[m] are cyclic copies), the
// position and the successor of every node (-1 for nodes that are not selected) and the cost of
// inserting every node (its cost if it is not selected, kBlocked if it is). LM is a bucket queue
// indexed by -delta (deltas are integers), each bucket a linked list of moves in a pool; a bit
// mask marks the non-empty buckets, so the best moves are found by scanning the mask from the top.
class MoveListSearch::State {
public:
    State(const int* distances, const int* costs, int node_count, int target_count, int buckets);
    void setCandidates(const CandidateSets& candidates);  // restricts the search to candidate moves

    void reset(const std::vector<int>& closed_route);  // also clears LM and the counters
    int cost() const;
    std::vector<int> closedRoute() const { return {route_, route_ + m_ + 1}; }
    const MoveListCounters& counters() const { return counters_; }

    void evaluateAll();
    int takeBestApplicable(int& delta);
    void applyTaken(int id, MoveListVariant variant);
    void clearList();

private:
    const int* row(int node) const { return distances_ + static_cast<std::ptrdiff_t>(node) * n_; }
    int dist(int from, int to) const { return row(from)[to]; }
    int previousIndex(int position) const { return position == 0 ? m_ - 1 : position - 1; }
    void refreshSentinels();

    int status(const StoredMove& move) const;
    std::int64_t rank(const StoredMove& move) const;

    int allocate();
    void push(int a, int b, int c, int d, int delta, std::uint16_t type, bool inverted = false);

    void evaluatePairs(int edge, int begin, int end);
    void evaluatePairsWithEdge(int edge, int skip_edge);
    void evaluateExchangesAt(int position);
    void evaluateEntering(int node, int begin, int end);
    void reverse(int from, int to);

    // Candidate mode: only moves that add at least one candidate edge, generated from the lists.
    int nextIndex(int position) const { return position + 1 == m_ ? 0 : position + 1; }
    bool isIntra(int u, int v) const { return intra_member_[static_cast<std::size_t>(u) * n_ + v] != 0; }
    bool isInter(int u, int v) const { return inter_member_[static_cast<std::size_t>(u) * n_ + v] != 0; }
    std::int64_t edgeKey(int u, int v) const {
        return static_cast<std::int64_t>(std::min(u, v)) * n_ + std::max(u, v);
    }
    bool noCommonNode(int first_edge, int second_edge) const;
    void pushPair(int edge, int other, bool inverted);
    void pushExchange(int position, int entering);
    void evaluateAllCandidates();
    void candidatePairsWithEdge(int edge, int skip_edge);
    void candidateExchangesAt(int position);
    void candidateEntering(int node, int position);
    std::int64_t candidateRank(const StoredMove& move) const;

    const int* distances_;
    const int* costs_;
    int n_;
    int m_;
    MoveListCounters counters_;

    std::vector<int> route_storage_;
    std::vector<int> edge_storage_;
    int* route_;
    int* edge_;
    std::vector<int> pos_;
    std::vector<int> succ_;
    std::vector<int> insertion_cost_;
    std::vector<Found> found_;

    std::vector<StoredMove> pool_;
    int pool_used_ = 0;
    std::vector<int> head_;  // first move of every bucket (bucket = -delta), -1 if empty
    std::vector<std::uint64_t> nonempty_;
    int top_word_ = -1;  // no word above it has a bit set

    bool candidate_mode_ = false;
    std::vector<int> intra_offsets_, intra_nodes_;  // candidate lists (node order), compressed rows
    std::vector<int> inter_offsets_, inter_nodes_;
    std::vector<WeightedCandidate> inter_by_weight_;  // inter lists sorted by d(u, v) + cost(v)
    std::vector<std::uint8_t> intra_member_, inter_member_;  // n x n: is {u, v} a candidate edge
};

MoveListSearch::State::State(const int* distances, const int* costs, int node_count, int target_count,
                             int buckets)
    : distances_(distances),
      costs_(costs),
      n_(node_count),
      m_(target_count),
      route_storage_(static_cast<std::size_t>(target_count) + 2),
      edge_storage_(static_cast<std::size_t>(target_count) + 2),
      route_(route_storage_.data() + 1),
      edge_(edge_storage_.data() + 1),
      pos_(static_cast<std::size_t>(node_count), -1),
      succ_(static_cast<std::size_t>(node_count), -1),
      insertion_cost_(static_cast<std::size_t>(node_count), kBlocked),
      found_(static_cast<std::size_t>(node_count) + 2 * static_cast<std::size_t>(target_count) + 4),
      pool_(kInitialPool),
      head_(static_cast<std::size_t>(buckets), -1),
      nonempty_(static_cast<std::size_t>(buckets) / 64 + 1, 0) {}

void MoveListSearch::State::setCandidates(const CandidateSets& candidates) {
    const std::size_t n = static_cast<std::size_t>(n_);
    const auto build = [&](const std::vector<std::vector<int>>& lists, std::vector<int>& offsets,
                           std::vector<int>& nodes, std::vector<std::uint8_t>& member) {
        if (lists.size() != n) {
            throw std::invalid_argument("candidate lists must have one list per node");
        }
        offsets.assign(n + 1, 0);
        nodes.clear();
        member.assign(n * n, 0);
        for (std::size_t owner = 0; owner < n; ++owner) {
            int previous = -1;
            for (const int node : lists[owner]) {
                if (node <= previous || node >= n_ || static_cast<std::size_t>(node) == owner) {
                    throw std::invalid_argument("candidate lists must be sorted by node index, without the owner");
                }
                previous = node;
                nodes.push_back(node);
                member[owner * n + static_cast<std::size_t>(node)] = 1;
            }
            offsets[owner + 1] = static_cast<int>(nodes.size());
        }
        for (std::size_t owner = 0; owner < n; ++owner) {  // every listed pair must be listed both ways
            for (int entry = offsets[owner]; entry < offsets[owner + 1]; ++entry) {
                if (member[static_cast<std::size_t>(nodes[static_cast<std::size_t>(entry)]) * n + owner] == 0) {
                    throw std::invalid_argument("candidate lists must be symmetric");
                }
            }
        }
    };
    build(candidates.intra, intra_offsets_, intra_nodes_, intra_member_);
    build(candidates.inter, inter_offsets_, inter_nodes_, inter_member_);
    inter_by_weight_.clear();
    for (int owner = 0; owner < n_; ++owner) {
        const auto first = inter_by_weight_.size();
        for (int entry = inter_offsets_[owner]; entry < inter_offsets_[owner + 1]; ++entry) {
            const int node = inter_nodes_[entry];
            inter_by_weight_.push_back({node, dist(owner, node) + costs_[node]});
        }
        std::sort(inter_by_weight_.begin() + static_cast<std::ptrdiff_t>(first), inter_by_weight_.end(),
                  [](const WeightedCandidate& left, const WeightedCandidate& right) {
                      return left.weight != right.weight ? left.weight < right.weight : left.node < right.node;
                  });
    }
    candidate_mode_ = true;
}

void MoveListSearch::State::refreshSentinels() {
    route_[-1] = route_[m_ - 1];
    route_[m_] = route_[0];
    edge_[-1] = edge_[m_ - 1];
    edge_[m_] = edge_[0];
}

void MoveListSearch::State::reset(const std::vector<int>& closed_route) {
    clearList();
    counters_ = MoveListCounters{};
    std::fill(pos_.begin(), pos_.end(), -1);
    std::fill(succ_.begin(), succ_.end(), -1);
    for (int position = 0; position < m_; ++position) {
        const int node = closed_route[static_cast<std::size_t>(position)];
        if (node < 0 || node >= n_ || pos_[static_cast<std::size_t>(node)] != -1) {
            throw std::invalid_argument("local search received a route with invalid or repeated nodes");
        }
        route_[position] = node;
        pos_[static_cast<std::size_t>(node)] = position;
    }
    route_[m_] = route_[0];
    for (int position = 0; position < m_; ++position) {
        edge_[position] = dist(route_[position], route_[position + 1]);
        succ_[static_cast<std::size_t>(route_[position])] = route_[position + 1];
    }
    refreshSentinels();
    for (int node = 0; node < n_; ++node) {
        insertion_cost_[static_cast<std::size_t>(node)] = pos_[static_cast<std::size_t>(node)] < 0 ? costs_[node] : kBlocked;
    }
}

int MoveListSearch::State::cost() const {
    int total = 0;
    for (int position = 0; position < m_; ++position) {
        total += edge_[position] + costs_[route_[position]];
    }
    return total;
}

// Situation of a stored move; x -> y is an edge of the current solution exactly when
// succ_[x] == y. Both move types are evaluated without branches and the result is selected by
// the type, because the type of the next move in LM is unpredictable.
int MoveListSearch::State::status(const StoredMove& move) const {
    const int* succ = succ_.data();
    const int a = move.a;
    const int b = move.b;
    const int c = move.c;
    const int d = move.d;
    const int after_a = succ[a];
    const int after_b = succ[b];
    const int after_c = succ[c];
    const int after_d = succ[d];
    // 2-opt: both removed edges must exist; same relative direction (both as stored or both
    // reversed) makes the reconnection valid.
    const bool ab = after_a == b;
    const bool cd = after_c == d;
    const bool edges_exist = (ab | (after_b == a)) & (cd | (after_d == c));
    const int two_opt = static_cast<int>(edges_exist) + static_cast<int>(edges_exist & (ab == cd));
    // Exchange: b is not selected and a still lies between c and d (in either order).
    const bool between = ((after_a == d) & (after_c == a)) | ((after_a == c) & (after_d == a));
    const int exchange = 2 * static_cast<int>((after_b < 0) & between);
    return move.type == kTwoOpt ? two_opt : exchange;
}

// Position of an applicable move in the scan order of the plain steepest local search (2-opt
// moves "reverse route[i..j]" by (i, j), then exchanges by (position, node)); among moves with
// equal delta the earliest is applied, exactly like in the plain search.
std::int64_t MoveListSearch::State::rank(const StoredMove& move) const {
    if (candidate_mode_) {
        return candidateRank(move);
    }
    if (move.type == kTwoOpt) {
        const bool forward = succ_[move.a] == move.b;
        const int first_edge = forward ? pos_[move.a] : pos_[move.b];
        const int second_edge = forward ? pos_[move.c] : pos_[move.d];
        const int p = std::min(first_edge, second_edge);
        const int q = std::max(first_edge, second_edge);
        // Removing the edges at positions p < q is "reverse route[p+1..q]"; when q is the closing
        // edge it is also "reverse route[0..p]", which comes first in the scan order.
        return q == m_ - 1 ? static_cast<std::int64_t>(p) : static_cast<std::int64_t>(p + 1) * m_ + q;
    }
    return static_cast<std::int64_t>(m_) * m_ + static_cast<std::int64_t>(pos_[move.a]) * n_ + move.b;
}

// The pool only grows during a run (slots of removed moves are not reused: a free list would
// make every insertion wait for a dependent load); it is emptied together with LM.
int MoveListSearch::State::allocate() {
    if (pool_used_ == static_cast<int>(pool_.size())) {
        pool_.resize(pool_.size() * 2);
    }
    return pool_used_++;
}

void MoveListSearch::State::push(int a, int b, int c, int d, int delta, std::uint16_t type, bool inverted) {
    const int bucket = -delta;
    const int id = allocate();
    StoredMove& move = pool_[static_cast<std::size_t>(id)];
    move.a = static_cast<std::uint16_t>(a);
    move.b = static_cast<std::uint16_t>(b);
    move.c = static_cast<std::uint16_t>(c);
    move.d = static_cast<std::uint16_t>(d);
    move.next = head_[static_cast<std::size_t>(bucket)];
    move.type = type;
    move.inverted = static_cast<std::uint16_t>(inverted);
    head_[static_cast<std::size_t>(bucket)] = id;
    const int word = bucket >> 6;
    nonempty_[static_cast<std::size_t>(word)] |= std::uint64_t{1} << (bucket & 63);
    top_word_ = std::max(top_word_, word);
    ++counters_.inserted;
}

void MoveListSearch::State::clearList() {
    for (int word = 0; word <= top_word_; ++word) {
        for (std::uint64_t bits = nonempty_[static_cast<std::size_t>(word)]; bits != 0; bits &= bits - 1) {
            head_[static_cast<std::size_t>(word * 64 + lowestSetBit(bits))] = -1;
        }
        nonempty_[static_cast<std::size_t>(word)] = 0;
    }
    top_word_ = -1;
    pool_used_ = 0;
}

// Browses LM from the best delta. Invalid moves are removed, moves whose edges have a different
// relative direction are kept, and the first applicable move (the lowest rank among applicable
// moves with the best delta) is taken out of LM. Returns its pool index (-1 if there is none)
// and sets `delta`.
int MoveListSearch::State::takeBestApplicable(int& delta) {
    while (top_word_ >= 0 && nonempty_[static_cast<std::size_t>(top_word_)] == 0) {
        --top_word_;
    }
    for (int word = top_word_; word >= 0; --word) {
        std::uint64_t bits = nonempty_[static_cast<std::size_t>(word)];
        while (bits != 0) {
            const int bit = highestSetBit(bits);
            bits &= ~(std::uint64_t{1} << bit);
            const int bucket = word * 64 + bit;
            int* link = &head_[static_cast<std::size_t>(bucket)];
            int* best_link = nullptr;
            std::int64_t best_rank = std::numeric_limits<std::int64_t>::max();
            for (int id = *link; id >= 0; id = *link) {
                StoredMove& move = pool_[static_cast<std::size_t>(id)];
                ++counters_.checked;
                const int state = status(move);
                if (state == kInvalid) {
                    *link = move.next;
                    ++counters_.removed;
                    continue;
                }
                counters_.not_applicable += state == kNotNow;
                if (state == kApplicable) {
                    const std::int64_t position = rank(move);
                    if (position < best_rank) {
                        best_rank = position;
                        best_link = link;
                    }
                }
                link = &move.next;
            }
            int best = -1;
            if (best_link != nullptr) {
                best = *best_link;
                *best_link = pool_[static_cast<std::size_t>(best)].next;
            }
            if (head_[static_cast<std::size_t>(bucket)] < 0) {
                nonempty_[static_cast<std::size_t>(word)] &= ~(std::uint64_t{1} << bit);
            }
            if (best >= 0) {
                delta = -bucket;
                return best;
            }
        }
    }
    return -1;
}

// 2-opt moves removing the edge at position `edge` and an edge at a position in begin .. end,
// both reconnections: the applicable one, which adds (a, c) and (b, d), and the one with
// relatively inverted edges, which adds (a, d) and (b, c). The scan writes every move to found_
// but advances only past improving ones, so it has no data-dependent branches; the improving
// moves are added to LM afterwards.
void MoveListSearch::State::evaluatePairs(int edge, int begin, int end) {
    if (begin > end) {
        return;
    }
    const int* route = route_;
    const int* lengths = edge_;
    const int a = route[edge];
    const int b = route[edge + 1];
    const int* from_a = row(a);
    const int* from_b = row(b);
    const int ab = lengths[edge];
    Found* found = found_.data();
    int count = 0;
    for (int j = begin; j <= end; ++j) {
        const int c = route[j];
        const int d = route[j + 1];
        const int removed = ab + lengths[j];
        const int same = from_a[c] + from_b[d] - removed;
        const int inverted = from_a[d] + from_b[c] - removed;
        found[count] = {2 * j, same};
        count += static_cast<int>(same < 0);
        found[count] = {2 * j + 1, inverted};
        count += static_cast<int>(inverted < 0);
    }
    for (int k = 0; k < count; ++k) {
        const int j = found[k].index >> 1;
        const bool inverted = (found[k].index & 1) != 0;
        const int c = route[j];
        const int d = route[j + 1];
        push(a, b, inverted ? d : c, inverted ? c : d, found[k].delta, kTwoOpt, inverted);
    }
    counters_.evaluated += 2LL * (end - begin + 1);
}

// Every pair of route edges without a common node, in both reconnections, and every exchange.
void MoveListSearch::State::evaluateAll() {
    if (candidate_mode_) {
        evaluateAllCandidates();
        return;
    }
    ++counters_.full_evaluations;
    for (int i = 0; i + 2 < m_; ++i) {
        evaluatePairs(i, i + 2, i == 0 ? m_ - 2 : m_ - 1);  // the edge at m - 1 ends in route[0]
    }
    for (int position = 0; position < m_; ++position) {
        evaluateExchangesAt(position);
    }
}

// 2-opt moves that remove the edge at position `edge` together with any edge without a common
// node (positions edge + 2 .. edge - 2, cyclically), except the edge at `skip_edge`.
void MoveListSearch::State::evaluatePairsWithEdge(int edge, int skip_edge) {
    const int ranges[2][2] = {{edge + 2, edge == 0 ? m_ - 2 : m_ - 1}, {edge == m_ - 1 ? 1 : 0, edge - 2}};
    for (const auto& range : ranges) {
        if (skip_edge >= range[0] && skip_edge <= range[1]) {
            evaluatePairs(edge, range[0], skip_edge - 1);
            evaluatePairs(edge, skip_edge + 1, range[1]);
        } else {
            evaluatePairs(edge, range[0], range[1]);
        }
    }
}

// Exchanges replacing the node at `position` with every node that is not selected. The scan runs
// over whole rows of the distance matrix (four nodes at a time with SSE2); selected nodes have
// the insertion cost kBlocked, so they never give an improving move.
void MoveListSearch::State::evaluateExchangesAt(int position) {
    const int leaving = route_[position];
    const int before = route_[position - 1];
    const int after = route_[position + 1];
    const int* from_before = row(before);
    const int* from_after = row(after);
    const int* insertion_cost = insertion_cost_.data();
    const int removed = edge_[position - 1] + edge_[position] + costs_[leaving];
    const int n = n_;
    Found* found = found_.data();
    int count = 0;
    int node = 0;
#ifdef LM_SEARCH_SSE2
    const __m128i limit = _mm_set1_epi32(removed);
    alignas(16) int sums[4];
    for (; node + 4 <= n; node += 4) {
        const __m128i sum = _mm_add_epi32(
            _mm_add_epi32(_mm_loadu_si128(reinterpret_cast<const __m128i*>(from_before + node)),
                          _mm_loadu_si128(reinterpret_cast<const __m128i*>(from_after + node))),
            _mm_loadu_si128(reinterpret_cast<const __m128i*>(insertion_cost + node)));
        const int improving = _mm_movemask_ps(_mm_castsi128_ps(_mm_cmplt_epi32(sum, limit)));
        if (improving != 0) {
            _mm_store_si128(reinterpret_cast<__m128i*>(sums), sum);
            for (int lane = 0; lane < 4; ++lane) {
                found[count] = {node + lane, sums[lane] - removed};
                count += (improving >> lane) & 1;
            }
        }
    }
#endif
    for (; node < n; ++node) {
        const int delta = from_before[node] + from_after[node] + insertion_cost[node] - removed;
        found[count] = {node, delta};
        count += static_cast<int>(delta < 0);
    }
    for (int k = 0; k < count; ++k) {
        push(leaving, found[k].index, before, after, found[k].delta, kExchange);
    }
    counters_.evaluated += n - m_;
}

// Exchanges in which the newly unselected `node` replaces the node at a position in begin .. end.
void MoveListSearch::State::evaluateEntering(int node, int begin, int end) {
    if (begin > end) {
        return;
    }
    const int* route = route_;
    const int* lengths = edge_;
    const int* costs = costs_;
    const int* from_node = row(node);
    const int node_cost = costs[node];
    Found* found = found_.data();
    int count = 0;
    for (int position = begin; position <= end; ++position) {
        const int delta = from_node[route[position - 1]] + from_node[route[position + 1]] + node_cost -
                          lengths[position - 1] - lengths[position] - costs[route[position]];
        found[count] = {position, delta};
        count += static_cast<int>(delta < 0);
    }
    for (int k = 0; k < count; ++k) {
        const int position = found[k].index;
        push(route[position], node, route[position - 1], route[position + 1], found[k].delta, kExchange);
    }
    counters_.evaluated += end - begin + 1;
}

// Reverses route[from..to] and updates edge lengths, positions and successors. The edges inside
// the segment keep their lengths in reverse order; only the two edges at its ends are new.
void MoveListSearch::State::reverse(int from, int to) {
    std::reverse(route_ + from, route_ + to + 1);
    std::reverse(edge_ + from, edge_ + to);
    const int before = previousIndex(from);
    route_[m_] = route_[0];
    edge_[before] = dist(route_[before], route_[before + 1]);
    edge_[to] = dist(route_[to], route_[to + 1]);
    refreshSentinels();
    for (int position = from; position <= to; ++position) {
        const int node = route_[position];
        pos_[static_cast<std::size_t>(node)] = position;
        succ_[static_cast<std::size_t>(node)] = route_[position + 1];
    }
    succ_[static_cast<std::size_t>(route_[before])] = route_[before + 1];
}

void MoveListSearch::State::applyTaken(int id, MoveListVariant variant) {
    const StoredMove move = pool_[static_cast<std::size_t>(id)];
    ++counters_.applied;
    const int m = m_;
    if (move.type == kTwoOpt) {
        ++counters_.applied_two_opt;
        counters_.applied_inverted += move.inverted;
        const bool forward = succ_[move.a] == move.b;
        const int first_edge = forward ? pos_[move.a] : pos_[move.b];
        const int second_edge = forward ? pos_[move.c] : pos_[move.d];
        const int p = std::min(first_edge, second_edge);
        const int q = std::max(first_edge, second_edge);
        if (q == m - 1) {
            reverse(0, p);
        } else {
            reverse(p + 1, q);
        }
        if (variant == MoveListVariant::NewMoves) {
            // The new edges are at positions p and q. Pairs of two old edges keep their deltas;
            // only their applicability may change, which is checked when LM is browsed.
            // The four end nodes have a new neighbour, so their exchanges change.
            if (candidate_mode_) {
                candidatePairsWithEdge(p, -1);
                candidatePairsWithEdge(q, p);
                candidateExchangesAt(p);
                candidateExchangesAt(nextIndex(p));
                candidateExchangesAt(q);
                candidateExchangesAt(nextIndex(q));
            } else {
                evaluatePairsWithEdge(p, -1);
                evaluatePairsWithEdge(q, p);
                evaluateExchangesAt(p);
                evaluateExchangesAt(nextIndex(p));
                evaluateExchangesAt(q);
                evaluateExchangesAt(nextIndex(q));
            }
        }
        return;
    }

    const int leaving = move.a;
    const int entering = move.b;
    const int position = pos_[leaving];
    const int before = previousIndex(position);
    const int after = position + 1 == m ? 0 : position + 1;
    route_[position] = entering;
    route_[m] = route_[0];
    edge_[before] = dist(route_[before], entering);
    edge_[position] = dist(entering, route_[position + 1]);
    refreshSentinels();
    pos_[entering] = position;
    pos_[leaving] = -1;
    succ_[route_[before]] = entering;
    succ_[entering] = route_[position + 1];
    succ_[leaving] = -1;
    insertion_cost_[entering] = kBlocked;
    insertion_cost_[leaving] = costs_[leaving];
    if (variant == MoveListVariant::NewMoves && candidate_mode_) {
        candidatePairsWithEdge(before, -1);  // new edge (route[before], entering)
        candidatePairsWithEdge(position, -1);  // new edge (entering, route[after])
        candidateExchangesAt(before);
        candidateExchangesAt(position);
        candidateExchangesAt(after);
        candidateEntering(leaving, position);  // the removed node may now enter elsewhere
    } else if (variant == MoveListVariant::NewMoves) {
        evaluatePairsWithEdge(before, -1);        // new edge (route[before], entering)
        evaluatePairsWithEdge(position, before);  // new edge (entering, route[after])
        evaluateExchangesAt(before);
        evaluateExchangesAt(position);
        evaluateExchangesAt(after);
        // The removed node may now enter at the other positions: position + 2 .. position - 2,
        // cyclically.
        const int first = position + 2;
        const int last = position + m - 2;
        if (first >= m) {
            evaluateEntering(leaving, first - m, last - m);
        } else if (last < m) {
            evaluateEntering(leaving, first, last);
        } else {
            evaluateEntering(leaving, first, m - 1);
            evaluateEntering(leaving, 0, last - m);
        }
    }
}

// ------------------------------------------------------------------ candidate mode
//
// A 2-opt move removes two edges and adds two edges, each joining an endpoint of one removed edge
// with an endpoint of the other. It is a candidate move when one of the added edges is a candidate
// edge {x, w}. The moves adding {x, w} remove one edge at x (x -> x+ or x- -> x) and one at w
// (w -> w+ or w- -> w): four combinations, two in the reconnection applicable now (x and w both
// tails or both heads of their removed edges) and two with relatively inverted edges.

bool MoveListSearch::State::noCommonNode(int first_edge, int second_edge) const {
    int gap = second_edge - first_edge;
    if (gap < 0) {
        gap += m_;
    }
    return gap > 1 && gap < m_ - 1;
}

// The 2-opt move removing the edges at positions `edge` (a -> b) and `other` (c -> d): applicable
// now (adds (a, c), (b, d)) or with relatively inverted edges (adds (a, d), (b, c)).
void MoveListSearch::State::pushPair(int edge, int other, bool inverted) {
    const int a = route_[edge];
    const int b = route_[edge + 1];
    const int c = route_[other];
    const int d = route_[other + 1];
    const int removed = edge_[edge] + edge_[other];
    ++counters_.evaluated;
    if (!inverted) {
        const int delta = dist(a, c) + dist(b, d) - removed;
        if (delta < 0) {
            push(a, b, c, d, delta, kTwoOpt, false);
        }
    } else {
        const int delta = dist(a, d) + dist(b, c) - removed;
        if (delta < 0) {
            push(a, b, d, c, delta, kTwoOpt, true);
        }
    }
}

// Exchange: `entering` (not selected) replaces the node at `position`.
void MoveListSearch::State::pushExchange(int position, int entering) {
    const int leaving = route_[position];
    const int before = route_[position - 1];
    const int after = route_[position + 1];
    ++counters_.evaluated;
    const int delta = dist(before, entering) + dist(entering, after) + costs_[entering] - edge_[position - 1] -
                      edge_[position] - costs_[leaving];
    if (delta < 0) {
        push(leaving, entering, before, after, delta, kExchange);
    }
}

// All candidate moves of the solution: for every candidate edge {x, w} between selected nodes (once,
// x < w) the up to four 2-opt moves adding it - a move adding two candidate edges is generated from
// the one with the smaller key only - and every candidate exchange.
void MoveListSearch::State::evaluateAllCandidates() {
    ++counters_.full_evaluations;
    for (int x = 0; x < n_; ++x) {
        const int px = pos_[x];
        if (px < 0) {
            continue;
        }
        const int x_out = px;
        const int x_in = previousIndex(px);
        const int xs = route_[px + 1];
        const int xp = route_[px - 1];
        for (int entry = intra_offsets_[x]; entry < intra_offsets_[x + 1]; ++entry) {
            const int w = intra_nodes_[entry];
            const int pw = pos_[w];
            if (w <= x || pw < 0) {
                continue;
            }
            const int w_out = pw;
            const int w_in = previousIndex(pw);
            const int ws = route_[pw + 1];
            const int wp = route_[pw - 1];
            const std::int64_t key = edgeKey(x, w);
            const auto here = [&](int u, int v) { return !isIntra(u, v) || edgeKey(u, v) > key; };
            if (noCommonNode(x_out, w_out) && here(xs, ws)) {
                pushPair(x_out, w_out, false);  // adds (x, w), (xs, ws)
            }
            if (noCommonNode(x_in, w_in) && here(xp, wp)) {
                pushPair(x_in, w_in, false);  // adds (xp, wp), (x, w)
            }
            if (noCommonNode(x_out, w_in) && here(xs, wp)) {
                pushPair(x_out, w_in, true);  // adds (x, w), (xs, wp)
            }
            if (noCommonNode(x_in, w_out) && here(xp, ws)) {
                pushPair(x_in, w_out, true);  // adds (xp, ws), (x, w)
            }
        }
    }
    for (int position = 0; position < m_; ++position) {
        candidateExchangesAt(position);
    }
}

// Candidate 2-opt moves that remove the edge x -> y at position `edge` (except together with the
// edge at `skip_edge`), each once: first those adding a candidate edge at x, then those adding one
// at y whose edge at x is not a candidate edge.
void MoveListSearch::State::candidatePairsWithEdge(int edge, int skip_edge) {
    const int x = route_[edge];
    const int y = route_[edge + 1];
    for (int entry = intra_offsets_[x]; entry < intra_offsets_[x + 1]; ++entry) {
        const int w = intra_nodes_[entry];
        const int pw = pos_[w];
        if (pw < 0 || w == y) {
            continue;
        }
        const int w_out = pw;
        const int w_in = previousIndex(pw);
        if (w_out != skip_edge && noCommonNode(edge, w_out)) {
            pushPair(edge, w_out, false);  // adds (x, w), (y, ws)
        }
        if (w_in != skip_edge && noCommonNode(edge, w_in)) {
            pushPair(edge, w_in, true);  // adds (x, w), (y, wp)
        }
    }
    for (int entry = intra_offsets_[y]; entry < intra_offsets_[y + 1]; ++entry) {
        const int w = intra_nodes_[entry];
        const int pw = pos_[w];
        if (pw < 0 || w == x) {
            continue;
        }
        const int w_out = pw;
        const int w_in = previousIndex(pw);
        if (w_in != skip_edge && noCommonNode(edge, w_in) && !isIntra(x, route_[pw - 1])) {
            pushPair(edge, w_in, false);  // adds (x, wp), (y, w)
        }
        if (w_out != skip_edge && noCommonNode(edge, w_out) && !isIntra(x, route_[pw + 1])) {
            pushPair(edge, w_out, true);  // adds (x, ws), (y, w)
        }
    }
}

// Candidate exchanges replacing the node at `position`: the entering node is a candidate of the
// node before or of the node after it (each entering node once). An exchange entering v via the
// list of `before` has delta = weight(before, v) + d(v, after) - removed >= weight - removed, and the
// lists are sorted by weight, so a scan stops at the first entry that cannot improve; this skips no
// improving move. The same holds for the list of `after`.
void MoveListSearch::State::candidateExchangesAt(int position) {
    const int leaving = route_[position];
    const int before = route_[position - 1];
    const int after = route_[position + 1];
    const int* from_before = row(before);
    const int* from_after = row(after);
    const int removed = edge_[position - 1] + edge_[position] + costs_[leaving];
    const WeightedCandidate* entries = inter_by_weight_.data();
    for (int entry = inter_offsets_[before]; entry < inter_offsets_[before + 1]; ++entry) {
        const WeightedCandidate candidate = entries[entry];
        if (candidate.weight >= removed) {
            break;
        }
        if (pos_[candidate.node] < 0) {
            ++counters_.evaluated;
            const int delta = candidate.weight + from_after[candidate.node] - removed;
            if (delta < 0) {
                push(leaving, candidate.node, before, after, delta, kExchange);
            }
        }
    }
    for (int entry = inter_offsets_[after]; entry < inter_offsets_[after + 1]; ++entry) {
        const WeightedCandidate candidate = entries[entry];
        if (candidate.weight >= removed) {
            break;
        }
        if (pos_[candidate.node] < 0 && !isInter(before, candidate.node)) {
            ++counters_.evaluated;
            const int delta = from_before[candidate.node] + candidate.weight - removed;
            if (delta < 0) {
                push(leaving, candidate.node, before, after, delta, kExchange);
            }
        }
    }
}

// Candidate exchanges inserting the newly unselected `node` next to one of its candidates, except at
// the positions position - 1 .. position + 1 (evaluated already). A position whose both neighbours
// are candidates of `node` is generated from the node before it only.
void MoveListSearch::State::candidateEntering(int node, int position) {
    const int before = previousIndex(position);
    const int after = nextIndex(position);
    for (int entry = inter_offsets_[node]; entry < inter_offsets_[node + 1]; ++entry) {
        const int w = inter_nodes_[entry];
        const int pw = pos_[w];
        if (pw < 0) {
            continue;
        }
        const int behind_w = nextIndex(pw);  // w is the node before this position
        if (behind_w != before && behind_w != position && behind_w != after) {
            pushExchange(behind_w, node);
        }
        const int ahead_w = previousIndex(pw);  // w is the node after this position
        if (ahead_w != before && ahead_w != position && ahead_w != after && !isInter(node, route_[ahead_w - 1])) {
            pushExchange(ahead_w, node);
        }
    }
}

// Position of an applicable candidate move in the scan order of the assignment-4 candidate search:
// for f = 0 .. m-1 the 2-opt groups B(f) (the list of S[f-1]) and C(f) (the list of S[f]) of the
// moves "reverse S[f..j]", then for every position p the exchange groups of the node before p and of
// the node after p; each list in node order. A move counts at its first occurrence.
std::int64_t MoveListSearch::State::candidateRank(const StoredMove& move) const {
    const std::int64_t n = n_;
    const auto index_in = [](const std::vector<int>& offsets, const std::vector<int>& nodes, int owner, int node) {
        const auto first = nodes.begin() + offsets[static_cast<std::size_t>(owner)];
        const auto last = nodes.begin() + offsets[static_cast<std::size_t>(owner) + 1];
        return static_cast<std::int64_t>(std::lower_bound(first, last, node) - first);
    };
    if (move.type == kTwoOpt) {
        const bool forward = succ_[move.a] == move.b;
        const int first_edge = forward ? pos_[move.a] : pos_[move.b];
        const int second_edge = forward ? pos_[move.c] : pos_[move.d];
        const int p = std::min(first_edge, second_edge);
        const int q = std::max(first_edge, second_edge);
        const int i = q == m_ - 1 ? 0 : p + 1;  // the move is "reverse S[i..j]"
        const int j = q == m_ - 1 ? p : q;
        const int a = route_[i - 1];
        const int b = route_[i];
        const int c = route_[j];
        const int d = route_[j + 1];
        if (isIntra(a, c)) {
            return 2 * i * n + index_in(intra_offsets_, intra_nodes_, a, c);  // group B(i)
        }
        return (2 * i + 1) * n + index_in(intra_offsets_, intra_nodes_, b, d);  // group C(i)
    }
    const std::int64_t m = m_;
    const int position = pos_[move.a];
    const int before = route_[position - 1];
    const int after = route_[position + 1];
    if (isInter(before, move.b)) {
        return (2 * m + 2 * position) * n + index_in(inter_offsets_, inter_nodes_, before, move.b);
    }
    return (2 * m + 2 * position + 1) * n + index_in(inter_offsets_, inter_nodes_, after, move.b);
}

MoveListSearch::MoveListSearch(const DistanceMatrix& distances, std::vector<int> node_costs)
    : distances_(distances),
      costs_(std::move(node_costs)),
      node_count_(static_cast<int>(costs_.size())),
      target_count_(std::max(1, static_cast<int>(std::ceil(costs_.size() / 2.0)))) {
    initialise(nullptr);
}

MoveListSearch::MoveListSearch(const DistanceMatrix& distances, std::vector<int> node_costs,
                               const CandidateSets& candidates)
    : distances_(distances),
      costs_(std::move(node_costs)),
      node_count_(static_cast<int>(costs_.size())),
      target_count_(std::max(1, static_cast<int>(std::ceil(costs_.size() / 2.0)))) {
    initialise(&candidates);
}

void MoveListSearch::initialise(const CandidateSets* candidates) {
    if (node_count_ < 3 || distances_.size() != node_count_) {
        throw std::invalid_argument("instance must contain at least 3 nodes and match the distance matrix");
    }
    if (node_count_ > kMaxNodes) {
        throw std::invalid_argument("the list-of-moves search supports at most 65535 nodes");
    }
    int max_distance = 0;
    int max_cost = 0;
    for (int from = 0; from < node_count_; ++from) {
        max_cost = std::max(max_cost, costs_[static_cast<std::size_t>(from)]);
        for (int to = 0; to < node_count_; ++to) {
            if (distances_(from, to) < 0 || costs_[static_cast<std::size_t>(from)] < 0) {
                throw std::invalid_argument("distances and node costs must be non-negative");
            }
            max_distance = std::max(max_distance, distances_(from, to));
        }
    }
    // A 2-opt move gains at most 2 * max distance, an exchange at most 2 * max distance + max cost.
    if (2LL * max_distance + max_cost >= kBlocked) {
        throw std::invalid_argument("distances and node costs are too large for the list of moves");
    }
    const int buckets = 2 * max_distance + max_cost + 1;
    state_ = std::make_unique<State>(distances_.row(0), costs_.data(), node_count_, target_count_, buckets);
    if (candidates != nullptr) {
        state_->setCandidates(*candidates);
    }
}

MoveListSearch::~MoveListSearch() = default;

Result MoveListSearch::run(const Result& initial, MoveListVariant variant, MoveListCounters* counters) {
    if (initial.route.size() != static_cast<std::size_t>(target_count_) + 1 ||
        initial.route.front() != initial.route.back()) {
        throw std::invalid_argument("local search received an invalid closed route");
    }
    State& state = *state_;
    state.reset(initial.route);
    int current_cost = state.cost();
    state.evaluateAll();
    const long long initial_inserted = state.counters().inserted;
    bool fresh = true;  // LM holds a complete evaluation of the current solution
    while (true) {
        int delta = 0;
        const int id = state.takeBestApplicable(delta);
        if (id >= 0) {
            state.applyTaken(id, variant);
            current_cost += delta;
            fresh = false;
            continue;
        }
        // No applicable move in LM. With NewMoves LM contains every improving move, so this is a
        // local optimum; the alternative algorithm evaluates the whole neighbourhood again, and
        // stops when that evaluation gives no applicable improving move.
        if (variant == MoveListVariant::NewMoves || fresh) {
            break;
        }
        state.clearList();
        state.evaluateAll();
        fresh = true;
    }

    std::vector<int> route = state.closedRoute();
    int total = 0;
    for (std::size_t index = 0; index + 1 < route.size(); ++index) {
        total += costs_[static_cast<std::size_t>(route[index])] + distances_(route[index], route[index + 1]);
    }
    if (total != current_cost) {
        throw std::logic_error("list-of-moves search: accumulated deltas disagree with the objective");
    }
    if (counters != nullptr) {
        *counters = state.counters();
        counters->initial_inserted = initial_inserted;
    }
    return {std::move(route), total};
}
