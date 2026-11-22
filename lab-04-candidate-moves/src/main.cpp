#include "distance_matrix.hpp"
#include "instance.hpp"
#include "solution_space.hpp"
#include "tsp_solver.hpp"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr int kRuns = 200;              // local-search runs per method and instance
constexpr int kListTimingRepeats = 25;  // timed candidate-list constructions per method

struct Options {
    std::string data_dir;
    unsigned int seed = 20260404U;
    std::vector<int> candidate_counts = {1, 5, 10, 15, 20, 30, 50};
    std::vector<std::string> instances;
    bool ranking_experiment = false;
};

struct TimeStats {
    double average_ms = 0.0;
    double minimum_ms = 0.0;
    double maximum_ms = 0.0;
};

// One local-search configuration: the full neighbourhood (candidate_count == 0) or candidate
// moves built from the candidate_count "nearest" vertices according to `definition`.
struct Method {
    std::string id;
    std::string label;
    int candidate_count = 0;
    CandidateDefinition definition;
    std::unique_ptr<TSPSolver> solver;
    double candidate_list_ms = 0.0;  // median time of building the candidate lists
    std::vector<double> run_ms;      // local-search time of every run
    TimeStats time;
    SolutionSpace space;

    bool usesCandidates() const { return candidate_count > 0; }
};

const NearestMetric kMetrics[] = {NearestMetric::Distance, NearestMetric::Cost, NearestMetric::DistancePlusCost};

const char* metricId(NearestMetric metric) {
    switch (metric) {
        case NearestMetric::Distance:
            return "distance";
        case NearestMetric::Cost:
            return "cost";
        case NearestMetric::DistancePlusCost:
            return "distance_plus_cost";
    }
    return "unknown";
}

std::string definitionLabel(const CandidateDefinition& definition) {
    return std::string("intra=") + metricId(definition.intra) + ", inter=" + metricId(definition.inter);
}

void printRoute(const std::vector<int>& route) {
    for (std::size_t index = 0; index < route.size(); ++index) {
        if (index > 0) {
            std::cout << ' ';
        }
        std::cout << route[index];
    }
    std::cout << '\n';
}

bool isValidRoute(const Result& result, int node_count, int target_count) {
    if (result.route.size() != static_cast<std::size_t>(target_count + 1) ||
        result.route.front() != result.route.back()) {
        return false;
    }

    std::vector<char> seen(static_cast<std::size_t>(node_count), 0);
    for (std::size_t index = 0; index + 1 < result.route.size(); ++index) {
        const int node = result.route[index];
        if (node < 0 || node >= node_count || seen[static_cast<std::size_t>(node)]) {
            return false;
        }
        seen[static_cast<std::size_t>(node)] = 1;
    }
    return true;
}

TimeStats summarizeTimes(const std::vector<double>& times) {
    if (times.empty()) {
        throw std::runtime_error("no run times recorded");
    }

    double sum = 0.0;
    double minimum = times.front();
    double maximum = times.front();
    for (double time : times) {
        sum += time;
        minimum = std::min(minimum, time);
        maximum = std::max(maximum, time);
    }
    return {sum / static_cast<double>(times.size()), minimum, maximum};
}

std::ofstream openOutput(const fs::path& path) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path.string());
    }
    return out;
}

Method makeMethod(std::string id, std::string label, int candidate_count, CandidateDefinition definition,
                  const DistanceMatrix& distances, const std::vector<int>& costs) {
    Method method;
    method.id = std::move(id);
    method.label = std::move(label);
    method.candidate_count = candidate_count;
    method.definition = definition;
    // The full neighbourhood never reads the candidate lists, so any valid list size will do.
    method.solver = std::make_unique<TSPSolver>(distances, costs, std::max(candidate_count, 1), definition);
    return method;
}

std::vector<Result> makeStartingSolutions(const std::string& instance_name, const Options& options,
                                          const TSPSolver& solver) {
    const unsigned int start_seed = options.seed ^ static_cast<unsigned int>(instance_name == "TSPB" ? 0xB00B : 0xA11A);
    std::mt19937 rng(start_seed);
    std::vector<Result> starts;
    starts.reserve(kRuns);
    for (int run = 0; run < kRuns; ++run) {
        starts.push_back(solver.randomStartingSolution(rng));
    }
    return starts;
}

// Median wall-clock time of building the candidate lists of every candidate-move method. The
// constructions are done in rounds over all methods, like the local-search runs below.
void measureCandidateLists(std::vector<Method>& methods, const DistanceMatrix& distances,
                           const std::vector<int>& costs) {
    std::vector<std::vector<double>> samples(methods.size());
    for (int repeat = 0; repeat <= kListTimingRepeats; ++repeat) {
        for (std::size_t index = 0; index < methods.size(); ++index) {
            if (!methods[index].usesCandidates()) {
                continue;
            }
            const TSPSolver solver(distances, costs, methods[index].candidate_count, methods[index].definition);
            if (repeat > 0) {  // round 0 only warms up caches and the allocator
                samples[index].push_back(solver.candidateListMilliseconds());
            }
        }
    }
    for (std::size_t index = 0; index < methods.size(); ++index) {
        auto& values = samples[index];
        if (values.empty()) {
            continue;
        }
        std::nth_element(values.begin(), values.begin() + static_cast<std::ptrdiff_t>(values.size() / 2), values.end());
        methods[index].candidate_list_ms = values[values.size() / 2];
    }
}

// Runs every method from every starting solution. The runs are interleaved (for each start,
// each method once), so that changes of the CPU clock during the experiment affect all methods
// alike. Only the local search itself is timed.
void runMethods(std::vector<Method>& methods, const std::vector<Result>& starts, int node_count, int target_count) {
    for (std::size_t run = 0; run < starts.size(); ++run) {
        for (auto& method : methods) {
            const auto begin = std::chrono::steady_clock::now();
            const Result result = method.solver->steepestLocalSearch(starts[run], method.usesCandidates());
            const auto end = std::chrono::steady_clock::now();
            method.run_ms.push_back(std::chrono::duration<double, std::milli>(end - begin).count());
            if (!isValidRoute(result, node_count, target_count)) {
                throw std::runtime_error("invalid route produced by " + method.id);
            }
            method.space.addSolution(result);
        }
        if (run == 0 || (run + 1) % 50 == 0) {
            std::cout << "  run " << (run + 1) << '/' << starts.size() << " done for all " << methods.size()
                      << " methods\n";
        }
    }
    for (auto& method : methods) {
        method.time = summarizeTimes(method.run_ms);
    }
}

// Main experiment: the full-neighbourhood baseline and candidate moves with the default
// definition of "nearest" for every candidate-list size.
void runInstance(const std::string& instance_name, const Options& options, const fs::path& lab_dir) {
    const std::string data_path = findDataFile(instance_name, options.data_dir);
    const std::vector<Node> nodes = loadInstance(data_path);
    const DistanceMatrix distances(nodes);
    const std::vector<int> costs = nodeCosts(nodes);
    const int node_count = static_cast<int>(nodes.size());
    for (int candidate_count : options.candidate_counts) {
        if (candidate_count <= 0 || candidate_count >= node_count) {
            throw std::invalid_argument("candidate count must be positive and smaller than the instance size");
        }
    }

    std::vector<Method> methods;
    methods.push_back(makeMethod("steepest_2opt", "Steepest local search - full neighborhood", 0, {}, distances, costs));
    for (int candidate_count : options.candidate_counts) {
        methods.push_back(makeMethod("candidate_k" + std::to_string(candidate_count),
                                     "Steepest local search - candidate moves (k=" + std::to_string(candidate_count) + ")",
                                     candidate_count, {}, distances, costs));
    }
    const int target_count = methods.front().solver->targetCount();
    const std::vector<Result> starts = makeStartingSolutions(instance_name, options, *methods.front().solver);

    std::cout << "=== " << instance_name << " ===\n"
              << "Loaded " << node_count << " nodes from " << data_path << '\n'
              << "Selecting " << target_count << " nodes per solution, " << kRuns << " runs per method\n";
    measureCandidateLists(methods, distances, costs);
    runMethods(methods, starts, node_count, target_count);

    const fs::path evaluation_dir = lab_dir / "evaluation";
    const fs::path results_dir = evaluation_dir / "results";
    const fs::path plots_dir = evaluation_dir / "plots";
    fs::create_directories(results_dir);
    fs::create_directories(plots_dir);

    std::ofstream times = openOutput(evaluation_dir / (instance_name + "_times.csv"));
    times << "method_name,candidate_count,average_ms,minimum_ms,maximum_ms,candidate_list_ms\n" << std::fixed
          << std::setprecision(6);
    std::ofstream stats_out = openOutput(evaluation_dir / (instance_name + "_stats.csv"));
    stats_out << "method_name,candidate_count,min,max,avg,sd\n" << std::fixed << std::setprecision(2);

    for (const auto& method : methods) {
        const Stats stats = method.space.stats();
        times << method.id << ',' << method.candidate_count << ',' << method.time.average_ms << ','
              << method.time.minimum_ms << ',' << method.time.maximum_ms << ',' << method.candidate_list_ms << '\n';
        stats_out << method.id << ',' << method.candidate_count << ',' << stats.min << ',' << stats.max << ','
                  << stats.avg << ',' << stats.sd << '\n';

        const Result& best = method.space.bestSolution();
        std::cout << "*** " << method.label << " ***\n"
                  << "Min: " << stats.min << "\nMax: " << stats.max << "\nAvg: " << stats.avg << "\nSd: " << stats.sd
                  << "\nTime average/min/max (ms): " << method.time.average_ms << "/" << method.time.minimum_ms << "/"
                  << method.time.maximum_ms << "\nCandidate lists (ms): " << method.candidate_list_ms
                  << "\nBest route: ";
        printRoute(best.route);

        method.space.writeBestSolutionCsv((results_dir / (instance_name + "_" + method.id + ".csv")).string());
        method.space.writeWorstSolutionCsv((results_dir / (instance_name + "_" + method.id + "_worst.csv")).string());
        method.space.writeSvg((plots_dir / (instance_name + "_" + method.id + ".svg")).string(), nodes,
                              instance_name + " " + method.label);
        method.space.writeWorstSvg((plots_dir / (instance_name + "_" + method.id + "_worst.svg")).string(), nodes,
                                   instance_name + " " + method.label + " (worst)");
    }
}

// Additional experiment: every combination of the "nearest" definition for 2-opt (intra) and
// exchange (inter) candidates - distance, cost or distance + cost - for every list size, plus
// the full-neighbourhood baseline, all interleaved in one session.
void runRankingExperiment(const std::string& instance_name, const Options& options, const fs::path& lab_dir) {
    const std::string data_path = findDataFile(instance_name, options.data_dir);
    const std::vector<Node> nodes = loadInstance(data_path);
    const DistanceMatrix distances(nodes);
    const std::vector<int> costs = nodeCosts(nodes);
    const int node_count = static_cast<int>(nodes.size());
    for (int candidate_count : options.candidate_counts) {
        if (candidate_count <= 0 || candidate_count >= node_count) {
            throw std::invalid_argument("candidate count must be positive and smaller than the instance size");
        }
    }

    std::vector<Method> methods;
    methods.push_back(makeMethod("full", "full neighborhood", 0, {}, distances, costs));
    for (NearestMetric intra : kMetrics) {
        for (NearestMetric inter : kMetrics) {
            const CandidateDefinition definition{intra, inter};
            for (int candidate_count : options.candidate_counts) {
                methods.push_back(makeMethod(std::string(metricId(intra)) + "__" + metricId(inter) + "__k" +
                                                 std::to_string(candidate_count),
                                             definitionLabel(definition) + ", k=" + std::to_string(candidate_count),
                                             candidate_count, definition, distances, costs));
            }
        }
    }
    const int target_count = methods.front().solver->targetCount();
    const std::vector<Result> starts = makeStartingSolutions(instance_name, options, *methods.front().solver);

    std::cout << "=== ranking experiment " << instance_name << " ===\n"
              << methods.size() << " methods (3 x 3 definitions of nearest x " << options.candidate_counts.size()
              << " list sizes + full neighborhood), " << kRuns << " runs each\n";
    measureCandidateLists(methods, distances, costs);
    runMethods(methods, starts, node_count, target_count);

    const fs::path evaluation_dir = lab_dir / "evaluation";
    fs::create_directories(evaluation_dir);
    std::ofstream times = openOutput(evaluation_dir / (instance_name + "_ranking_times.csv"));
    times << "intra,inter,candidate_count,average_ms,minimum_ms,maximum_ms,candidate_list_ms\n" << std::fixed
          << std::setprecision(6);
    std::ofstream stats_out = openOutput(evaluation_dir / (instance_name + "_ranking_stats.csv"));
    stats_out << "intra,inter,candidate_count,min,max,avg,sd\n" << std::fixed << std::setprecision(2);
    std::ofstream best_out = openOutput(evaluation_dir / (instance_name + "_ranking_best.csv"));
    best_out << "intra,inter,candidate_count,objective,route\n";

    for (const auto& method : methods) {
        const std::string intra = method.usesCandidates() ? metricId(method.definition.intra) : "none";
        const std::string inter = method.usesCandidates() ? metricId(method.definition.inter) : "none";
        const Stats stats = method.space.stats();
        const Result& best = method.space.bestSolution();
        times << intra << ',' << inter << ',' << method.candidate_count << ',' << method.time.average_ms << ','
              << method.time.minimum_ms << ',' << method.time.maximum_ms << ',' << method.candidate_list_ms << '\n';
        stats_out << intra << ',' << inter << ',' << method.candidate_count << ',' << stats.min << ',' << stats.max
                  << ',' << stats.avg << ',' << stats.sd << '\n';
        best_out << intra << ',' << inter << ',' << method.candidate_count << ',' << best.total_cost << ',';
        for (std::size_t index = 0; index < best.route.size(); ++index) {
            best_out << (index > 0 ? " " : "") << best.route[index];
        }
        best_out << '\n';
        std::cout << method.label << ": avg=" << stats.avg << " min=" << stats.min << " max=" << stats.max
                  << " time_avg_ms=" << method.time.average_ms << " lists_ms=" << method.candidate_list_ms << '\n';
    }
}

std::vector<int> parseCandidateCounts(const std::string& value) {
    std::vector<int> counts;
    std::stringstream stream(value);
    std::string token;
    while (std::getline(stream, token, ',')) {
        if (token.empty()) {
            throw std::invalid_argument("candidate-counts contains an empty value");
        }
        counts.push_back(std::stoi(token));
    }
    if (counts.empty()) {
        throw std::invalid_argument("candidate-counts cannot be empty");
    }
    return counts;
}

Options parseOptions(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--data-dir" && index + 1 < argc) {
            options.data_dir = argv[++index];
        } else if (argument == "--candidate-counts" && index + 1 < argc) {
            options.candidate_counts = parseCandidateCounts(argv[++index]);
        } else if (argument == "--candidate-count" && index + 1 < argc) {
            options.candidate_counts = {std::stoi(argv[++index])};
        } else if (argument == "--seed" && index + 1 < argc) {
            options.seed = static_cast<unsigned int>(std::stoul(argv[++index]));
        } else if (argument == "--ranking-experiment") {
            options.ranking_experiment = true;
        } else if (argument == "--help") {
            std::cout << "Usage: lab04 [--data-dir DIR] [--candidate-counts K1,K2,...] "
                         "[--candidate-count K] [--seed N] [--ranking-experiment] [TSPA] [TSPB]\n";
            std::exit(0);
        } else {
            options.instances.push_back(argument);
        }
    }
    if (options.instances.empty()) {
        options.instances = {"TSPA", "TSPB"};
    }
    return options;
}

fs::path resolveLabDirectory(const char* executable) {
    fs::path resolved = fs::current_path();
    for (fs::path cursor = fs::absolute(executable).parent_path();; cursor = cursor.parent_path()) {
        if (fs::exists(cursor / "src" / "main.cpp") && fs::exists(cursor / "CMakeLists.txt")) {
            resolved = cursor;
            break;
        }
        if (!cursor.has_parent_path() || cursor == cursor.root_path()) {
            break;
        }
    }
    return resolved;
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const Options options = parseOptions(argc, argv);
        const fs::path lab_dir = resolveLabDirectory(argv[0]);
        for (const auto& instance : options.instances) {
            if (options.ranking_experiment) {
                runRankingExperiment(instance, options, lab_dir);
            } else {
                runInstance(instance, options, lab_dir);
            }
        }
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << '\n';
        return 1;
    }
}
