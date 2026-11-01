#include "distance_matrix.hpp"
#include "instance.hpp"
#include "solution_space.hpp"
#include "tsp_solver.hpp"

#include <chrono>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

struct MethodConfig {
    std::string id;
    std::string label;
    bool greedy_start = false;
    SearchStrategy strategy = SearchStrategy::Steepest;
    IntraNeighborhood neighborhood = IntraNeighborhood::NodeExchange;
};

struct MethodRun {
    MethodConfig config;
    SolutionSpace space;
    long long time_ms = 0;
};

struct Options {
    std::string data_dir;
    unsigned int seed = 20260303U;
    std::vector<std::string> instances;
};

namespace {

const std::vector<MethodConfig> METHOD_CONFIGS = {
    {"random_steepest_node", "Random start - steepest - node exchange", false, SearchStrategy::Steepest, IntraNeighborhood::NodeExchange},
    {"random_steepest_2opt", "Random start - steepest - 2-opt", false, SearchStrategy::Steepest, IntraNeighborhood::TwoOpt},
    {"random_greedy_node", "Random start - greedy - node exchange", false, SearchStrategy::Greedy, IntraNeighborhood::NodeExchange},
    {"random_greedy_2opt", "Random start - greedy - 2-opt", false, SearchStrategy::Greedy, IntraNeighborhood::TwoOpt},
    {"greedy_steepest_node", "Greedy start - steepest - node exchange", true, SearchStrategy::Steepest, IntraNeighborhood::NodeExchange},
    {"greedy_steepest_2opt", "Greedy start - steepest - 2-opt", true, SearchStrategy::Steepest, IntraNeighborhood::TwoOpt},
    {"greedy_greedy_node", "Greedy start - greedy - node exchange", true, SearchStrategy::Greedy, IntraNeighborhood::NodeExchange},
    {"greedy_greedy_2opt", "Greedy start - greedy - 2-opt", true, SearchStrategy::Greedy, IntraNeighborhood::TwoOpt},
};

void printRoute(const std::vector<int>& route) {
    for (std::size_t i = 0; i < route.size(); ++i) {
        if (i > 0) {
            std::cout << ' ';
        }
        std::cout << route[i];
    }
    std::cout << '\n';
}

bool isValidRoute(const Result& result, int node_count, int target_count) {
    if (result.route.size() != static_cast<std::size_t>(target_count + 1) ||
        result.route.front() != result.route.back()) {
        return false;
    }

    std::vector<char> seen(static_cast<std::size_t>(node_count), 0);
    for (std::size_t i = 0; i + 1 < result.route.size(); ++i) {
        const int node = result.route[i];
        if (node < 0 || node >= node_count || seen[static_cast<std::size_t>(node)]) {
            return false;
        }
        seen[static_cast<std::size_t>(node)] = 1;
    }
    return true;
}

void writeTimes(const fs::path& path, const std::vector<MethodRun>& methods) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path.string());
    }
    out << "method_name,time\n";
    for (const auto& method : methods) {
        out << method.config.id << ',' << method.time_ms << '\n';
    }
}

void writeStats(const fs::path& path, const std::vector<MethodRun>& methods) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path.string());
    }
    out << "method_name,min,max,avg,sd\n";
    out << std::fixed << std::setprecision(2);
    for (const auto& method : methods) {
        const Stats stats = method.space.stats();
        out << method.config.id << ',' << stats.min << ',' << stats.max << ',' << stats.avg << ',' << stats.sd << '\n';
    }
}

void runInstance(const std::string& instance_name, const Options& options, const fs::path& lab_dir) {
    const std::string data_path = findDataFile(instance_name, options.data_dir);
    const std::vector<Node> nodes = loadInstance(data_path);
    const DistanceMatrix distances(nodes);
    const TSPSolver solver(distances.matrix(), nodes);
    const int node_count = static_cast<int>(nodes.size());

    std::cout << "=== " << instance_name << " ===\n";
    std::cout << "Loaded " << node_count << " nodes from " << data_path << '\n';
    std::cout << "Selecting " << solver.targetCount() << " nodes per solution\n";
    std::cout << "Local-search runs per method: " << node_count << "\n";

    std::vector<Result> greedy_starts;
    greedy_starts.reserve(static_cast<std::size_t>(node_count));
    for (int start = 0; start < node_count; ++start) {
        greedy_starts.push_back(solver.bestGreedyStartingSolution(start));
    }

    std::vector<MethodRun> methods;
    for (const auto& config : METHOD_CONFIGS) {
        methods.push_back({config, {}, 0});
    }

    for (std::size_t method_index = 0; method_index < methods.size(); ++method_index) {
        auto& method = methods[method_index];
        const unsigned int method_seed = options.seed
                                         ^ static_cast<unsigned int>(instance_name == "TSPB" ? 0xB00B : 0xA11A)
                                         ^ static_cast<unsigned int>((method_index + 1) * 7919);
        std::mt19937 rng(method_seed);
        const auto begin = std::chrono::steady_clock::now();

        for (int run = 0; run < node_count; ++run) {
            if (run == 0 || (run + 1) % 50 == 0 || run + 1 == node_count) {
                std::cout << method.config.id << " iteration " << (run + 1) << '/' << node_count << '\n';
            }

            const Result initial = method.config.greedy_start
                                       ? greedy_starts[static_cast<std::size_t>(run)]
                                       : solver.randomStartingSolution(rng);
            const Result result = solver.localSearch(initial, method.config.strategy,
                                                     method.config.neighborhood, rng);
            if (!isValidRoute(result, node_count, solver.targetCount())) {
                throw std::runtime_error("invalid route produced by " + method.config.id);
            }
            method.space.addSolution(result);
        }

        const auto end = std::chrono::steady_clock::now();
        method.time_ms = std::chrono::duration_cast<std::chrono::milliseconds>(end - begin).count();
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
                  << "Min: " << stats.min << "\nMax: " << stats.max << "\nAvg: " << stats.avg
                  << "\nSd: " << stats.sd << "\nTime (ms): " << method.time_ms << '\n'
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

Options parseOptions(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        if (argument == "--data-dir" && i + 1 < argc) {
            options.data_dir = argv[++i];
        } else if (argument == "--seed" && i + 1 < argc) {
            options.seed = static_cast<unsigned int>(std::stoul(argv[++i]));
        } else if (argument == "--help") {
            std::cout << "Usage: lab03 [--data-dir DIR] [--seed N] [TSPA] [TSPB]\n";
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
            runInstance(instance, options, lab_dir);
        }
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << '\n';
        return 1;
    }
}
