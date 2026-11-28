#include "msls_ils.hpp"

#include <algorithm>
#include <chrono>
#include <utility>

namespace {

using Clock = std::chrono::steady_clock;

double millisecondsSince(Clock::time_point begin) {
    return std::chrono::duration<double, std::milli>(Clock::now() - begin).count();
}

int randomInt(std::mt19937& rng, int low, int high) {
    return std::uniform_int_distribution<int>(low, high)(rng);
}

}  // namespace

LocalSearchMethods::LocalSearchMethods(const TSPSolver& solver, MoveListSearch& local_search, int node_count)
    : solver_(solver),
      local_search_(local_search),
      node_count_(node_count),
      selected_(static_cast<std::size_t>(node_count), 0) {}

Result LocalSearchMethods::localSearch(const std::vector<int>& open_route) {
    Result start;
    start.route = open_route;
    start.route.push_back(open_route.front());
    return local_search_.run(start, MoveListVariant::NewMoves);
}

MslsRun LocalSearchMethods::multipleStart(int iterations, std::mt19937& rng) {
    MslsRun run;
    run.local_optima.reserve(static_cast<std::size_t>(iterations));
    run.local_search_ms.reserve(static_cast<std::size_t>(iterations));
    const auto begin = Clock::now();
    for (int iteration = 0; iteration < iterations; ++iteration) {
        const auto started = Clock::now();
        Result result = local_search_.run(solver_.randomStartingSolution(rng), MoveListVariant::NewMoves);
        run.local_search_ms.push_back(millisecondsSince(started));
        run.local_optima.push_back(result.total_cost);
        if (iteration == 0 || result.total_cost < run.best.total_cost) {
            run.best = std::move(result);
        }
    }
    run.ms = millisecondsSince(begin);
    return run;
}

IlsRun LocalSearchMethods::iterated(double time_limit_ms, const Perturbation& perturbation, std::mt19937& rng) {
    IlsRun run;
    const auto begin = Clock::now();
    Result current = local_search_.run(solver_.randomStartingSolution(rng), MoveListVariant::NewMoves);
    run.local_searches = 1;
    std::vector<int> route;
    while (millisecondsSince(begin) < time_limit_ms) {
        route.assign(current.route.begin(), current.route.end() - 1);
        perturb(route, perturbation, rng);
        Result candidate = localSearch(route);
        ++run.local_searches;
        if (candidate.total_cost < current.total_cost) {
            current = std::move(candidate);
            ++run.improvements;
        }
    }
    run.best = std::move(current);
    run.ms = millisecondsSince(begin);
    return run;
}

void LocalSearchMethods::perturb(std::vector<int>& route, const Perturbation& perturbation, std::mt19937& rng) {
    for (int step = 0; step < perturbation.double_bridges; ++step) {
        doubleBridge(route, rng);
    }
    if (perturbation.segment_length > 0) {
        replaceSegment(route, perturbation.segment_length, rng);
    }
    for (int step = 0; step < perturbation.random_moves; ++step) {
        randomMove(route, rng);
    }
}

// S = A B C D with three distinct random cuts 0 < i < j < k <= m - 1 (A = S[0..i-1], B = S[i..j-1],
// C = S[j..k-1], D = S[k..m-1]) becomes A C B D. The edges at the three cuts are replaced and no
// segment is reversed, so a single 2-opt move cannot undo it.
void LocalSearchMethods::doubleBridge(std::vector<int>& route, std::mt19937& rng) {
    const int m = static_cast<int>(route.size());
    if (m < 4) {
        return;
    }
    int cuts[3];
    do {
        for (int& cut : cuts) {
            cut = randomInt(rng, 1, m - 1);
        }
        std::sort(cuts, cuts + 3);
    } while (cuts[0] == cuts[1] || cuts[1] == cuts[2]);
    buffer_.clear();
    buffer_.insert(buffer_.end(), route.begin(), route.begin() + cuts[0]);            // A
    buffer_.insert(buffer_.end(), route.begin() + cuts[1], route.begin() + cuts[2]);  // C
    buffer_.insert(buffer_.end(), route.begin() + cuts[0], route.begin() + cuts[1]);  // B
    buffer_.insert(buffer_.end(), route.begin() + cuts[2], route.end());              // D
    route.swap(buffer_);
}

// `length` consecutive positions, starting at a random one, get distinct random nodes drawn from the
// nodes that were not selected before this step (the replaced nodes are not candidates).
void LocalSearchMethods::replaceSegment(std::vector<int>& route, int length, std::mt19937& rng) {
    const int m = static_cast<int>(route.size());
    markSelection(route);
    pool_.clear();
    for (int node = 0; node < node_count_; ++node) {
        if (!selected_[static_cast<std::size_t>(node)]) {
            pool_.push_back(node);
        }
    }
    const int count = std::min({length, m, static_cast<int>(pool_.size())});
    const int start = randomInt(rng, 0, m - 1);
    for (int step = 0; step < count; ++step) {
        const int pick = randomInt(rng, step, static_cast<int>(pool_.size()) - 1);
        std::swap(pool_[static_cast<std::size_t>(step)], pool_[static_cast<std::size_t>(pick)]);
        route[static_cast<std::size_t>((start + step) % m)] = pool_[static_cast<std::size_t>(step)];
    }
}

// A random 2-opt move (reverse S[i..j] for random i < j) or a random exchange (a random selected node
// replaced by a random not selected node), each with probability 1/2.
void LocalSearchMethods::randomMove(std::vector<int>& route, std::mt19937& rng) {
    const int m = static_cast<int>(route.size());
    if (randomInt(rng, 0, 1) == 0) {
        int first = randomInt(rng, 0, m - 1);
        int second = randomInt(rng, 0, m - 1);
        while (second == first) {
            second = randomInt(rng, 0, m - 1);
        }
        if (first > second) {
            std::swap(first, second);
        }
        std::reverse(route.begin() + first, route.begin() + second + 1);
        return;
    }
    if (m >= node_count_) {
        return;  // every node is selected: no exchange exists
    }
    markSelection(route);
    int node = randomInt(rng, 0, node_count_ - 1);
    while (selected_[static_cast<std::size_t>(node)]) {
        node = randomInt(rng, 0, node_count_ - 1);
    }
    route[static_cast<std::size_t>(randomInt(rng, 0, m - 1))] = node;
}

void LocalSearchMethods::markSelection(const std::vector<int>& route) {
    std::fill(selected_.begin(), selected_.end(), 0);
    for (const int node : route) {
        selected_[static_cast<std::size_t>(node)] = 1;
    }
}
