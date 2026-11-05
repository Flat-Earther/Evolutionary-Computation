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
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

constexpr int RUNS = 200;

struct MethodConfig {
    std::string id;
    std::string label;
    bool use_candidate_moves = false;
    int candidate_count = 0;
};

struct TimeStats {
    double average_ms = 0.0;
    double minimum_ms = 0.0;
    double maximum_ms = 0.0;
};

struct MethodRun {
    MethodConfig config;
    SolutionSpace space;
    TimeStats time;
};

struct RankingMethodConfig {
    std::string id;
    std::string label;
    int candidate_count = 0;
    CandidateRanking ranking = CandidateRanking::DistanceIntraPlusCostsInter;
};

struct RankingMethodRun {
    RankingMethodConfig config;
    SolutionSpace space;
    TimeStats time;
};

struct Options {
    std::string data_dir;
    unsigned int seed = 20260404U;
    std::vector<int> candidate_counts = {1, 5, 10, 15, 20, 30, 50};
    std::vector<std::string> instances;
    bool ranking_experiment = false;
};

namespace {

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

void writeTimes(const fs::path& path, const std::vector<MethodRun>& methods) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path.string());
    }
    out << "method_name,candidate_count,average_ms,minimum_ms,maximum_ms\n";
    out << std::fixed << std::setprecision(6);
    for (const auto& method : methods) {
        out << method.config.id << ',' << method.config.candidate_count << ',' << method.time.average_ms << ','
            << method.time.minimum_ms << ',' << method.time.maximum_ms << '\n';
    }
}

void writeStats(const fs::path& path, const std::vector<MethodRun>& methods) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path.string());
    }
    out << "method_name,candidate_count,min,max,avg,sd\n";
    out << std::fixed << std::setprecision(2);
    for (const auto& method : methods) {
        const Stats stats = method.space.stats();
        out << method.config.id << ',' << method.config.candidate_count << ',' << stats.min << ','
            << stats.max << ',' << stats.avg << ',' << stats.sd << '\n';
    }
}

void writeRankingTimes(const fs::path& path, const std::vector<RankingMethodRun>& methods) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path.string());
    }
    out << "method_name,candidate_count,ranking,average_ms,minimum_ms,maximum_ms\n";
    out << std::fixed << std::setprecision(6);
    for (const auto& method : methods) {
        out << method.config.id << ',' << method.config.candidate_count << ',' << method.config.label << ','
            << method.time.average_ms << ',' << method.time.minimum_ms << ',' << method.time.maximum_ms << '\n';
    }
}

void writeRankingStats(const fs::path& path, const std::vector<RankingMethodRun>& methods) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path.string());
    }
    out << "method_name,candidate_count,ranking,min,max,avg,sd\n";
    out << std::fixed << std::setprecision(2);
    for (const auto& method : methods) {
        const Stats stats = method.space.stats();
        out << method.config.id << ',' << method.config.candidate_count << ',' << method.config.label << ','
            << stats.min << ',' << stats.max << ',' << stats.avg << ',' << stats.sd << '\n';
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

std::vector<MethodConfig> makeMethodConfigs(const std::vector<int>& candidate_counts) {
    std::vector<MethodConfig> configs = {
        {"steepest_2opt", "Steepest local search - full neighborhood", false, 0},
    };
    for (int candidate_count : candidate_counts) {
        const std::string label = candidate_count == 1
                                      ? "Steepest local search - candidate moves (k=1, nearest)"
                                      : "Steepest local search - candidate moves (k=" + std::to_string(candidate_count) + ")";
        configs.push_back({"candidate_k" + std::to_string(candidate_count),
                           label,
                           true,
                           candidate_count});
    }
    return configs;
}

std::vector<RankingMethodConfig> makeRankingMethodConfigs(const std::vector<int>& candidate_counts) {
    std::vector<RankingMethodConfig> configs;
    for (int candidate_count : candidate_counts) {
        configs.push_back({"distance_intra_costs_inter_k" + std::to_string(candidate_count),
                           "Distance intra + costs inter",
                           candidate_count,
                           CandidateRanking::DistanceIntraPlusCostsInter});
        configs.push_back({"distance_plus_costs_all_k" + std::to_string(candidate_count),
                           "Distance + costs intra/inter",
                           candidate_count,
                           CandidateRanking::DistancePlusNodeCostsForAll});
    }
    return configs;
}

void runInstance(const std::string& instance_name, const Options& options, const fs::path& lab_dir) {
    const std::string data_path = findDataFile(instance_name, options.data_dir);
    const std::vector<Node> nodes = loadInstance(data_path);
    const DistanceMatrix distances(nodes);
    const int node_count = static_cast<int>(nodes.size());
    for (int candidate_count : options.candidate_counts) {
        if (candidate_count <= 0 || candidate_count >= node_count) {
            throw std::invalid_argument("candidate count must be positive and smaller than the instance size");
        }
    }
    const std::vector<MethodConfig> method_configs = makeMethodConfigs(options.candidate_counts);
    const TSPSolver start_solver(distances.matrix(), nodes, 1);

    std::cout << "=== " << instance_name << " ===\n";
    std::cout << "Loaded " << node_count << " nodes from " << data_path << '\n';
    std::cout << "Selecting " << start_solver.targetCount() << " nodes per solution\n";
    std::cout << "Candidate list sizes: ";
    for (std::size_t index = 0; index < options.candidate_counts.size(); ++index) {
        if (index > 0) {
            std::cout << ',';
        }
        std::cout << options.candidate_counts[index];
    }
    std::cout << '\n';
    std::cout << "Runs per method: " << RUNS << '\n';

    const unsigned int start_seed = options.seed
                                    ^ static_cast<unsigned int>(instance_name == "TSPB" ? 0xB00B : 0xA11A);
    std::mt19937 start_rng(start_seed);
    std::vector<Result> random_starts;
    random_starts.reserve(RUNS);
    for (int run = 0; run < RUNS; ++run) {
        random_starts.push_back(start_solver.randomStartingSolution(start_rng));
    }

    std::vector<MethodRun> methods;
    for (const auto& config : method_configs) {
        methods.push_back({config, {}, {}});
    }

    for (auto& method : methods) {
        const TSPSolver solver(distances.matrix(), nodes,
                               method.config.use_candidate_moves ? method.config.candidate_count : 1);
        std::vector<double> run_times;
        run_times.reserve(RUNS);

        for (int run = 0; run < RUNS; ++run) {
            if (run == 0 || (run + 1) % 50 == 0 || run + 1 == RUNS) {
                std::cout << method.config.id << " iteration " << (run + 1) << '/' << RUNS << '\n';
            }

            const auto begin = std::chrono::steady_clock::now();
            const Result result = solver.steepestLocalSearch(random_starts[static_cast<std::size_t>(run)],
                                                              method.config.use_candidate_moves);
            const auto end = std::chrono::steady_clock::now();
            run_times.push_back(std::chrono::duration<double, std::milli>(end - begin).count());

            if (!isValidRoute(result, node_count, solver.targetCount())) {
                throw std::runtime_error("invalid route produced by " + method.config.id);
            }
            method.space.addSolution(result);
        }
        method.time = summarizeTimes(run_times);
    }

    const fs::path evaluation_dir = lab_dir / "evaluation";
    const fs::path results_dir = evaluation_dir / "results";
    const fs::path plots_dir = evaluation_dir / "plots";
    fs::create_directories(results_dir);
    fs::create_directories(plots_dir);
    writeTimes(evaluation_dir / (instance_name + "_times.csv"), methods);
    writeStats(evaluation_dir / (instance_name + "_stats.csv"), methods);

    for (const auto& method : methods) {
        const Stats stats = method.space.stats();
        const Result& best = method.space.bestSolution();
        std::cout << "*** " << method.config.label << " ***\n"
                  << "Candidate count: " << method.config.candidate_count << '\n'
                  << "Min: " << stats.min << "\nMax: " << stats.max << "\nAvg: " << stats.avg
                  << "\nSd: " << stats.sd
                  << "\nTime average/min/max (ms): " << method.time.average_ms << "/"
                  << method.time.minimum_ms << "/" << method.time.maximum_ms << '\n'
                  << "Best route: ";
        printRoute(best.route);

        method.space.writeBestSolutionCsv((results_dir / (instance_name + "_" + method.config.id + ".csv")).string());
        method.space.writeWorstSolutionCsv(
            (results_dir / (instance_name + "_" + method.config.id + "_worst.csv")).string());
        method.space.writeSvg((plots_dir / (instance_name + "_" + method.config.id + ".svg")).string(), nodes,
                              instance_name + " " + method.config.label);
        method.space.writeWorstSvg(
            (plots_dir / (instance_name + "_" + method.config.id + "_worst.svg")).string(), nodes,
            instance_name + " " + method.config.label + " (worst)");
    }
}

void runRankingExperiment(const std::string& instance_name, const Options& options, const fs::path& lab_dir) {
    const std::string data_path = findDataFile(instance_name, options.data_dir);
    const std::vector<Node> nodes = loadInstance(data_path);
    const DistanceMatrix distances(nodes);
    const int node_count = static_cast<int>(nodes.size());
    for (int candidate_count : options.candidate_counts) {
        if (candidate_count <= 0 || candidate_count >= node_count) {
            throw std::invalid_argument("candidate count must be positive and smaller than the instance size");
        }
    }

    const std::vector<RankingMethodConfig> configs = makeRankingMethodConfigs(options.candidate_counts);
    const TSPSolver start_solver(distances.matrix(), nodes, 1);
    const unsigned int start_seed = options.seed
                                    ^ static_cast<unsigned int>(instance_name == "TSPB" ? 0xB00B : 0xA11A);
    std::mt19937 start_rng(start_seed);
    std::vector<Result> random_starts;
    random_starts.reserve(RUNS);
    for (int run = 0; run < RUNS; ++run) {
        random_starts.push_back(start_solver.randomStartingSolution(start_rng));
    }

    std::cout << "=== ranking experiment " << instance_name << " ===\n";
    std::cout << "Comparing the default ranking with node-cost ranking for both move types\n";
    std::cout << "Runs per method: " << RUNS << '\n';

    std::vector<RankingMethodRun> methods;
    for (const auto& config : configs) {
        methods.push_back({config, {}, {}});
    }

    for (auto& method : methods) {
        const TSPSolver solver(distances.matrix(), nodes, method.config.candidate_count, method.config.ranking);
        std::vector<double> run_times;
        run_times.reserve(RUNS);
        for (int run = 0; run < RUNS; ++run) {
            if (run == 0 || (run + 1) % 50 == 0 || run + 1 == RUNS) {
                std::cout << method.config.id << " iteration " << (run + 1) << '/' << RUNS << '\n';
            }

            const auto begin = std::chrono::steady_clock::now();
            const Result result = solver.steepestLocalSearch(
                random_starts[static_cast<std::size_t>(run)], true);
            const auto end = std::chrono::steady_clock::now();
            run_times.push_back(std::chrono::duration<double, std::milli>(end - begin).count());

            if (!isValidRoute(result, node_count, solver.targetCount())) {
                throw std::runtime_error("invalid route produced by " + method.config.id);
            }
            method.space.addSolution(result);
        }
        method.time = summarizeTimes(run_times);
        const Stats stats = method.space.stats();
        std::cout << method.config.label << " (k=" << method.config.candidate_count << ")"
                  << " min=" << stats.min << " max=" << stats.max << " avg=" << stats.avg
                  << " time_avg_ms=" << method.time.average_ms << '\n';
    }

    const fs::path evaluation_dir = lab_dir / "evaluation";
    fs::create_directories(evaluation_dir);
    writeRankingTimes(evaluation_dir / (instance_name + "_ranking_times.csv"), methods);
    writeRankingStats(evaluation_dir / (instance_name + "_ranking_stats.csv"), methods);
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
