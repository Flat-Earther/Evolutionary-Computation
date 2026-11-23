#include "distance_matrix.hpp"
#include "instance.hpp"
#include "lm_search.hpp"
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
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr int kRuns = 200;  // local-search runs per method and instance

struct Options {
    std::string data_dir;
    unsigned int seed = 20260404U;
    std::vector<std::string> instances;
};

enum class Kind {
    Full,            // steepest local search, full neighbourhood (baseline)
    MoveListNew,     // list of improving moves, new moves evaluated after every move
    MoveListAlt,     // list of improving moves, alternative algorithm
    Candidate,       // candidate moves (lab 4), for reference
};

struct Method {
    std::string id;
    std::string label;
    Kind kind = Kind::Full;
    std::vector<double> run_ms;
    std::vector<Result> results;
    double applied = 0;       // per-run averages of the work counters
    double evaluated = 0;
    MoveListCounters totals;  // sums over all runs (list-of-moves methods)
    int same_as_baseline = 0; // runs ending in exactly the baseline's local optimum
    SolutionSpace space;

    bool usesMoveList() const { return kind == Kind::MoveListNew || kind == Kind::MoveListAlt; }
};

void addCounters(MoveListCounters& total, const MoveListCounters& run) {
    total.evaluated += run.evaluated;
    total.inserted += run.inserted;
    total.initial_inserted += run.initial_inserted;
    total.checked += run.checked;
    total.removed += run.removed;
    total.not_applicable += run.not_applicable;
    total.full_evaluations += run.full_evaluations;
    total.applied += run.applied;
    total.applied_two_opt += run.applied_two_opt;
    total.applied_inverted += run.applied_inverted;
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

std::ofstream openOutput(const fs::path& path) {
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path.string());
    }
    return out;
}

void printRoute(const std::vector<int>& route) {
    for (std::size_t index = 0; index < route.size(); ++index) {
        std::cout << (index > 0 ? " " : "") << route[index];
    }
    std::cout << '\n';
}

void runInstance(const std::string& instance_name, const Options& options, const fs::path& lab_dir) {
    const std::string data_path = findDataFile(instance_name, options.data_dir);
    const std::vector<Node> nodes = loadInstance(data_path);
    const DistanceMatrix distances(nodes);
    const std::vector<int> costs = nodeCosts(nodes);
    const int node_count = static_cast<int>(nodes.size());

    const TSPSolver full(distances, costs, 1);
    const TSPSolver candidates(distances, costs, 10);
    MoveListSearch move_list(distances, costs);  // keeps LM between runs
    const int m = full.targetCount();
    const long long full_neighbourhood = static_cast<long long>(m) * (m - 1) / 2 - 1 +
                                         static_cast<long long>(m) * (node_count - m);

    std::vector<Method> methods(4);
    const auto describe = [](Method& method, std::string id, std::string label, Kind kind) {
        method.id = std::move(id);
        method.label = std::move(label);
        method.kind = kind;
    };
    describe(methods[0], "steepest_full", "Steepest local search - full neighbourhood (baseline)", Kind::Full);
    describe(methods[1], "lm_new_moves", "LM - new moves evaluated after each move", Kind::MoveListNew);
    describe(methods[2], "lm_alternative", "LM - alternative algorithm", Kind::MoveListAlt);
    describe(methods[3], "candidate_k10", "Candidate moves, K = 10 (lab 4)", Kind::Candidate);

    // The same 200 random starting solutions for every method (same generator as in lab 4).
    const unsigned int start_seed = options.seed ^ static_cast<unsigned int>(instance_name == "TSPB" ? 0xB00B : 0xA11A);
    std::mt19937 rng(start_seed);
    std::vector<Result> starts;
    for (int run = 0; run < kRuns; ++run) {
        starts.push_back(full.randomStartingSolution(rng));
    }

    std::cout << "=== " << instance_name << " ===\n"
              << "Loaded " << node_count << " nodes from " << data_path << "; " << m << " selected, " << kRuns
              << " runs per method\n";

    // Runs are interleaved (for every start, every method once) so that changes of the processor
    // clock affect all methods alike. Only the local search is timed.
    for (int run = 0; run < kRuns; ++run) {
        const Result& start = starts[static_cast<std::size_t>(run)];
        for (auto& method : methods) {
            long long applied = 0;
            MoveListCounters counters;
            const auto begin = std::chrono::steady_clock::now();
            Result result;
            switch (method.kind) {
                case Kind::Full:
                    result = full.steepestLocalSearch(start, false, &applied);
                    break;
                case Kind::Candidate:
                    result = candidates.steepestLocalSearch(start, true, &applied);
                    break;
                case Kind::MoveListNew:
                    result = move_list.run(start, MoveListVariant::NewMoves, &counters);
                    break;
                case Kind::MoveListAlt:
                    result = move_list.run(start, MoveListVariant::Alternative, &counters);
                    break;
            }
            const auto end = std::chrono::steady_clock::now();
            method.run_ms.push_back(std::chrono::duration<double, std::milli>(end - begin).count());

            if (!isValidRoute(result, node_count, m)) {
                throw std::runtime_error("invalid route produced by " + method.id);
            }
            if (method.usesMoveList()) {
                applied = counters.applied;
                addCounters(method.totals, counters);
                // Self-check: no move of the full neighbourhood improves the result.
                if (full.steepestLocalSearch(result, false).route != result.route) {
                    throw std::logic_error(method.id + " did not end in a local optimum");
                }
            }
            method.applied += static_cast<double>(applied) / kRuns;
            if (method.kind == Kind::Full) {
                method.evaluated += static_cast<double>((applied + 1) * full_neighbourhood) / kRuns;
            }
            // The baseline is the first method, so its result for this start is already stored.
            if (method.kind == Kind::Full || result.route == methods.front().results.back().route) {
                ++method.same_as_baseline;
            }
            method.results.push_back(result);
            method.space.addSolution(result);
        }
        if (run == 0 || (run + 1) % 50 == 0) {
            std::cout << "  run " << (run + 1) << '/' << kRuns << " done for all methods\n";
        }
    }

    const fs::path evaluation_dir = lab_dir / "evaluation";
    const fs::path results_dir = evaluation_dir / "results";
    const fs::path plots_dir = evaluation_dir / "plots";
    fs::create_directories(results_dir);
    fs::create_directories(plots_dir);
    std::ofstream stats_out = openOutput(evaluation_dir / (instance_name + "_stats.csv"));
    std::ofstream times_out = openOutput(evaluation_dir / (instance_name + "_times.csv"));
    std::ofstream work_out = openOutput(evaluation_dir / (instance_name + "_work.csv"));
    stats_out << "method_name,min,max,avg,sd\n" << std::fixed << std::setprecision(2);
    times_out << "method_name,average_ms,minimum_ms,maximum_ms\n" << std::fixed << std::setprecision(6);
    // Per-run averages; empty where a counter does not apply to the method.
    work_out << "method_name,applied,applied_two_opt,applied_inverted,evaluated,inserted,initial_inserted,checked,"
                "removed,not_applicable,full_evaluations,same_as_baseline\n"
             << std::fixed << std::setprecision(2);

    for (auto& method : methods) {
        const Stats stats = method.space.stats();
        const double average = [&] {
            double sum = 0;
            for (double time : method.run_ms) {
                sum += time;
            }
            return sum / static_cast<double>(method.run_ms.size());
        }();
        const double minimum = *std::min_element(method.run_ms.begin(), method.run_ms.end());
        const double maximum = *std::max_element(method.run_ms.begin(), method.run_ms.end());
        stats_out << method.id << ',' << stats.min << ',' << stats.max << ',' << stats.avg << ',' << stats.sd << '\n';
        times_out << method.id << ',' << average << ',' << minimum << ',' << maximum << '\n';
        const MoveListCounters& total = method.totals;
        const auto per_run = [](long long value) { return static_cast<double>(value) / kRuns; };
        work_out << method.id << ',' << method.applied << ',';
        if (method.usesMoveList()) {
            work_out << per_run(total.applied_two_opt) << ',' << per_run(total.applied_inverted) << ','
                     << per_run(total.evaluated) << ',' << per_run(total.inserted) << ','
                     << per_run(total.initial_inserted) << ',' << per_run(total.checked) << ','
                     << per_run(total.removed) << ',' << per_run(total.not_applicable) << ','
                     << per_run(total.full_evaluations);
        } else {
            work_out << ",,";
            if (method.kind == Kind::Full) {
                work_out << method.evaluated;  // (applied moves + 1) full neighbourhoods
            }
            work_out << ",,,,,,";
        }
        work_out << ',' << method.same_as_baseline << '\n';

        std::cout << "*** " << method.label << " ***\n"
                  << "Min: " << stats.min << "  Max: " << stats.max << "  Avg: " << stats.avg << "  Sd: " << stats.sd
                  << "\nTime average/min/max (ms): " << average << "/" << minimum << "/" << maximum
                  << "\nApplied moves: " << method.applied;
        if (method.kind == Kind::Full) {
            std::cout << "  evaluated: " << method.evaluated;
        }
        if (method.usesMoveList()) {
            std::cout << " (2-opt " << per_run(total.applied_two_opt) << ", with relatively inverted edges "
                      << per_run(total.applied_inverted) << ")  evaluated: " << per_run(total.evaluated)
                      << "\nLM: inserted " << per_run(total.inserted) << " (by the first evaluation "
                      << per_run(total.initial_inserted) << "), checked " << per_run(total.checked)
                      << " (removed " << per_run(total.removed) << ", kept as not applicable "
                      << per_run(total.not_applicable) << ")  full evaluations: " << per_run(total.full_evaluations);
        }
        std::cout << "\nRuns ending in the baseline's local optimum: " << method.same_as_baseline << '/' << kRuns
                  << "\nBest route: ";
        printRoute(method.space.bestSolution().route);

        method.space.writeBestSolutionCsv((results_dir / (instance_name + "_" + method.id + ".csv")).string());
        method.space.writeWorstSolutionCsv((results_dir / (instance_name + "_" + method.id + "_worst.csv")).string());
        method.space.writeSvg((plots_dir / (instance_name + "_" + method.id + ".svg")).string(), nodes,
                              instance_name + " " + method.label);
        method.space.writeWorstSvg((plots_dir / (instance_name + "_" + method.id + "_worst.svg")).string(), nodes,
                                   instance_name + " " + method.label + " (worst)");
    }
}

Options parseOptions(int argc, char** argv) {
    Options options;
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--data-dir" && index + 1 < argc) {
            options.data_dir = argv[++index];
        } else if (argument == "--seed" && index + 1 < argc) {
            options.seed = static_cast<unsigned int>(std::stoul(argv[++index]));
        } else if (argument == "--help") {
            std::cout << "Usage: lab05 [--data-dir DIR] [--seed N] [TSPA] [TSPB]\n";
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
