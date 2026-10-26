#include "distance_matrix.hpp"
#include "instance.hpp"
#include "solution_space.hpp"
#include "tsp_solver.hpp"

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <exception>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

struct MethodRun {
    std::string id;
    std::string result_stem;
    std::string label;
    std::function<Result(int)> solve;
    SolutionSpace space;
    long long time_ms = 0;
};

struct Options {
    std::string data_dir;
    double regret_weight = 1.0;
    double delta_weight = 1.0;
    std::vector<std::string> instances;
};

void writeTimes(const fs::path& path, const std::vector<MethodRun>& methods) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path.string());
    }
    out << "method_name,time\n";
    for (const auto& method : methods) {
        out << method.id << ',' << method.time_ms << '\n';
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
        out << method.id << ',' << stats.min << ',' << stats.max << ',' << stats.avg << ',' << stats.sd << '\n';
    }
}

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
    if (result.route.size() != static_cast<std::size_t>(target_count + 1) || result.route.front() != result.route.back()) {
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

void runInstance(const std::string& instance_name, const Options& options, const fs::path& lab_dir) {
    const std::string csv_path = findDataFile(instance_name, options.data_dir);
    const std::vector<Node> nodes = loadInstance(csv_path);
    const DistanceMatrix distances(nodes);
    TSPSolver solver(distances.matrix(), nodes, options.regret_weight, options.delta_weight);
    const int node_count = static_cast<int>(nodes.size());

    std::cout << "=== " << instance_name << " ===\n";
    std::cout << "Loaded " << node_count << " nodes from " << csv_path << "\n";
    std::cout << "Selecting " << solver.targetCount() << " nodes per solution\n";
    std::cout << "Weighted score: " << solver.regretWeight() << " * regret - " << solver.deltaWeight()
              << " * best_delta\n";

    std::vector<MethodRun> methods;
    methods.push_back({"random_sol", "random", "Random", [&](int) { return solver.randomSolution(); }, {}, 0});
    methods.push_back({"nn_at_end", "nn_end", "NN at the end", [&](int start) {
                           return solver.nearestNeighborEnd(start);
                       }, {}, 0});
    methods.push_back({"nn_flexible", "nn_flexible", "NN flexible", [&](int start) {
                           return solver.nearestNeighborFlexible(start);
                       }, {}, 0});
    methods.push_back({"greedy_cycle", "greedy_cycle", "Greedy cycle", [&](int start) {
                           return solver.greedyCycle(start);
                       }, {}, 0});
    methods.push_back({"regret2_path", "regret2_path", "2-regret path", [&](int start) {
                           return solver.regret2Flexible(start);
                       }, {}, 0});
    methods.push_back({"regret2_cycle", "regret2_cycle", "2-regret cycle", [&](int start) {
                           return solver.regret2Cycle(start);
                       }, {}, 0});
    methods.push_back({"weighted_path", "weighted_path", "Weighted regret path", [&](int start) {
                           return solver.weightedRegretFlexible(start);
                       }, {}, 0});
    methods.push_back({"weighted_cycle", "weighted_cycle", "Weighted regret cycle", [&](int start) {
                           return solver.weightedRegretCycle(start);
                       }, {}, 0});

    std::vector<long long> elapsed_ns(methods.size(), 0);
    for (int start = 0; start < node_count; ++start) {
        if ((start + 1) % 20 == 0 || start == 0) {
            std::cout << "Iteration " << (start + 1) << '/' << node_count << '\n';
        }

        for (std::size_t method_index = 0; method_index < methods.size(); ++method_index) {
            const auto begin = std::chrono::steady_clock::now();
            const Result result = methods[method_index].solve(start);
            const auto end = std::chrono::steady_clock::now();
            elapsed_ns[method_index] +=
                std::chrono::duration_cast<std::chrono::nanoseconds>(end - begin).count();

            if (!isValidRoute(result, node_count, solver.targetCount())) {
                throw std::runtime_error("invalid route produced by " + methods[method_index].id);
            }
            methods[method_index].space.addSolution(result);
        }
    }

    for (std::size_t i = 0; i < methods.size(); ++i) {
        methods[i].time_ms = elapsed_ns[i] / 1'000'000;
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
        std::cout << "*** " << method.label << " stats ***\n";
        std::cout << "Min: " << stats.min << "\nMax: " << stats.max << "\nAvg: " << stats.avg
                  << "\nSd: " << stats.sd << "\n";
        std::cout << "Time (ms): " << method.time_ms << "\n";
        std::cout << "Best route: ";
        printRoute(best.route);

        method.space.writeBestSolutionCsv((results_dir / (instance_name + "_" + method.result_stem + ".csv")).string());
        method.space.writeWorstSolutionCsv(
            (results_dir / (instance_name + "_" + method.result_stem + "_worst.csv")).string());
        method.space.writeSvg((plots_dir / (instance_name + "_" + method.result_stem + ".svg")).string(), nodes,
                              instance_name + " " + method.label);
        method.space.writeWorstSvg(
            (plots_dir / (instance_name + "_" + method.result_stem + "_worst.svg")).string(), nodes,
            instance_name + " " + method.label + " (worst)");
    }
    std::cout << '\n';
}

Options parseOptions(int argc, char** argv) {
    Options options;
    for (int i = 1; i < argc; ++i) {
        const std::string argument = argv[i];
        if (argument == "--data-dir" && i + 1 < argc) {
            options.data_dir = argv[++i];
        } else if (argument == "--regret-weight" && i + 1 < argc) {
            options.regret_weight = std::stod(argv[++i]);
        } else if (argument == "--delta-weight" && i + 1 < argc) {
            options.delta_weight = std::stod(argv[++i]);
        } else if (argument == "--help") {
            std::cout << "Usage: lab02 [--data-dir DIR] [--regret-weight W] [--delta-weight W] [TSPA] [TSPB]\n";
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
