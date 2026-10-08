#include "distance_matrix.hpp"
#include "instance.hpp"
#include "solution_space.hpp"
#include "tsp_solver.hpp"

#include <chrono>
#include <exception>
#include <filesystem>
#include <fstream>
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
    SolutionSpace space;
    long long time_ms = 0;
};

void writeTimes(const std::string& path, const std::vector<MethodRun>& methods) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path);
    }
    out << "method_name,time\n";
    for (const auto& method : methods) {
        out << method.id << "," << method.time_ms << "\n";
    }
}

void writeStats(const std::string& path, const std::vector<MethodRun>& methods) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path);
    }
    out << "method_name,min,max,avg,sd\n";
    out << std::fixed << std::setprecision(2);
    for (const auto& method : methods) {
        const Stats s = method.space.stats();
        out << method.id << "," << s.min << "," << s.max << "," << s.avg << "," << s.sd << "\n";
    }
}

void printRoute(const std::vector<int>& route) {
    for (std::size_t i = 0; i < route.size(); ++i) {
        if (i > 0) {
            std::cout << " ";
        }
        std::cout << route[i];
    }
    std::cout << "\n";
}

void runInstance(const std::string& instance_name, const std::string& data_dir, const fs::path& lab_dir) {
    const std::string csv_path = findDataFile(instance_name, data_dir);
    const std::vector<Node> nodes = loadInstance(csv_path);
    const DistanceMatrix distances(nodes);
    TSPSolver solver(distances.matrix(), nodes);
    const int n = static_cast<int>(nodes.size());

    std::cout << "=== " << instance_name << " ===\n";
    std::cout << "Loaded " << n << " nodes from " << csv_path << "\n";
    std::cout << "Selecting " << solver.targetCount() << " nodes per solution\n";

    MethodRun random_run{"random_sol", "random", "Random", {}, 0};
    MethodRun nn_end_run{"nn_at_end", "nn_end", "NN at the end", {}, 0};
    MethodRun nn_flex_run{"nn_flexible", "nn_flexible", "NN flexible", {}, 0};
    MethodRun greedy_run{"greedy_cycle", "greedy_cycle", "Greedy cycle", {}, 0};
    long long random_ns = 0;
    long long nn_end_ns = 0;
    long long nn_flex_ns = 0;
    long long greedy_ns = 0;

    for (int i = 0; i < n; ++i) {
        if ((i + 1) % 20 == 0 || i == 0) {
            std::cout << "Iteration " << (i + 1) << "/" << n << "\n";
        }

        auto start = std::chrono::steady_clock::now();
        random_run.space.addSolution(solver.randomSolution());
        auto end = std::chrono::steady_clock::now();
        random_ns += std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

        start = std::chrono::steady_clock::now();
        nn_end_run.space.addSolution(solver.nearestNeighborEnd(i));
        end = std::chrono::steady_clock::now();
        nn_end_ns += std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

        start = std::chrono::steady_clock::now();
        nn_flex_run.space.addSolution(solver.nearestNeighborFlexible(i));
        end = std::chrono::steady_clock::now();
        nn_flex_ns += std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();

        start = std::chrono::steady_clock::now();
        greedy_run.space.addSolution(solver.greedyCycle(i));
        end = std::chrono::steady_clock::now();
        greedy_ns += std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
    }

    random_run.time_ms = random_ns / 1'000'000;
    nn_end_run.time_ms = nn_end_ns / 1'000'000;
    nn_flex_run.time_ms = nn_flex_ns / 1'000'000;
    greedy_run.time_ms = greedy_ns / 1'000'000;

    std::vector<MethodRun> methods{random_run, nn_end_run, nn_flex_run, greedy_run};

    const fs::path evaluation_dir = lab_dir / "evaluation";
    const fs::path results_dir = evaluation_dir / "results";
    const fs::path plots_dir = evaluation_dir / "plots";
    fs::create_directories(results_dir);
    fs::create_directories(plots_dir);

    writeTimes((evaluation_dir / (instance_name + "_times.csv")).string(), methods);
    writeStats((evaluation_dir / (instance_name + "_stats.csv")).string(), methods);

    for (const auto& method : methods) {
        const Stats s = method.space.stats();
        const Result& best = method.space.bestSolution();
        std::cout << "*** " << method.label << " stats ***\n";
        std::cout << "Min: " << s.min << "\nMax: " << s.max << "\nAvg: " << s.avg << "\nSd: " << s.sd << "\n";
        std::cout << "Time (ms): " << method.time_ms << "\n";
        std::cout << "Best route: ";
        printRoute(best.route);

        method.space.writeBestSolutionCsv((results_dir / (instance_name + "_" + method.result_stem + ".csv")).string());
        method.space.writeSvg((plots_dir / (instance_name + "_" + method.result_stem + ".svg")).string(), nodes,
                              instance_name + " " + method.label);
    }
    std::cout << "\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        std::string data_dir;
        std::vector<std::string> instances;

        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--data-dir" && i + 1 < argc) {
                data_dir = argv[++i];
            } else {
                instances.push_back(arg);
            }
        }
        if (instances.empty()) {
            instances = {"TSPA", "TSPB"};
        }

        fs::path resolved_lab_dir = fs::current_path();
        for (fs::path cursor = fs::absolute(argv[0]).parent_path();; cursor = cursor.parent_path()) {
            if (fs::exists(cursor / "src" / "main.cpp") && fs::exists(cursor / "CMakeLists.txt")) {
                resolved_lab_dir = cursor;
                break;
            }
            if (!cursor.has_parent_path() || cursor == cursor.root_path()) {
                break;
            }
        }
        if (!fs::exists(resolved_lab_dir / "src" / "main.cpp")) {
            for (fs::path cursor = fs::current_path();; cursor = cursor.parent_path()) {
                if (fs::exists(cursor / "src" / "main.cpp") && fs::exists(cursor / "CMakeLists.txt")) {
                    resolved_lab_dir = cursor;
                    break;
                }
                if (!cursor.has_parent_path() || cursor == cursor.root_path()) {
                    break;
                }
            }
        }

        for (const auto& instance : instances) {
            runInstance(instance, data_dir, resolved_lab_dir);
        }
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        return 1;
    }
}
