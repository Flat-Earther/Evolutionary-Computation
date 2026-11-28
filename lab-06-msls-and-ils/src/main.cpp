#include "distance_matrix.hpp"
#include "instance.hpp"
#include "lm_search.hpp"
#include "msls_ils.hpp"
#include "solution_space.hpp"
#include "tsp_solver.hpp"

#include <algorithm>
#include <cmath>
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

constexpr int kRuns = 20;             // runs of MSLS and of ILS per instance
constexpr int kMslsIterations = 400;  // local-search runs in one run of MSLS

struct Options {
    std::string data_dir;
    unsigned int seed = 20260404U;
    bool perturbation_experiment = false;
    std::vector<std::string> instances;
};

// The perturbation used by ILS (see Perturbation in msls_ils.hpp).
Perturbation chosenPerturbation() {
    return {"db1_seg4", "Double bridge + segment of 4", 1, 4, 0};
}

// Perturbations compared in the additional experiment (--perturbation-experiment).
std::vector<Perturbation> comparedPerturbations() {
    return {
        {"db1", "Double bridge", 1, 0, 0},
        {"seg4", "Segment of 4", 0, 4, 0},
        {"random10", "10 random moves", 0, 0, 10},
        {"db1_seg2", "Double bridge + segment of 2", 1, 2, 0},
        chosenPerturbation(),
        {"db1_seg8", "Double bridge + segment of 8", 1, 8, 0},
        {"db2_seg4", "2 double bridges + segment of 4", 2, 4, 0},
    };
}

std::mt19937 makeRng(unsigned int seed, unsigned int instance_code, unsigned int stream, int run) {
    std::seed_seq sequence{seed, instance_code, stream, static_cast<unsigned int>(run)};
    return std::mt19937(sequence);
}

// Minimum, maximum, average and standard deviation (average and sd rounded to 2 decimals, as in
// SolutionSpace::stats).
Stats statsOf(const std::vector<double>& values) {
    Stats stats;
    stats.min = *std::min_element(values.begin(), values.end());
    stats.max = *std::max_element(values.begin(), values.end());
    double sum = 0;
    for (double value : values) {
        sum += value;
    }
    const double average = sum / static_cast<double>(values.size());
    double squares = 0;
    for (double value : values) {
        squares += (value - average) * (value - average);
    }
    stats.avg = std::round(average * 100.0) / 100.0;
    stats.sd = std::round(std::sqrt(squares / static_cast<double>(values.size())) * 100.0) / 100.0;
    return stats;
}

double average(const std::vector<double>& values) {
    double sum = 0;
    for (double value : values) {
        sum += value;
    }
    return sum / static_cast<double>(values.size());
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

// Every reported solution must be a valid local optimum of the steepest local search.
void checkResult(const Result& result, const TSPSolver& solver, int node_count, const std::string& what) {
    if (!isValidRoute(result, node_count, solver.targetCount())) {
        throw std::runtime_error(what + " produced an invalid route");
    }
    if (solver.steepestLocalSearch(result, false).route != result.route) {
        throw std::logic_error(what + " did not end in a local optimum");
    }
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

struct IlsSeries {
    Perturbation perturbation;
    SolutionSpace space;
    std::vector<double> ms;
    std::vector<double> local_searches;
    std::vector<double> improvements;
    std::vector<IlsRun> runs;
};

// Points of a trajectory shown as snapshots: the first local optimum, the first solutions that closed
// at least half and at least 90% of the gap between it and the final solution, and the final solution.
std::vector<std::size_t> snapshotPoints(const std::vector<TrajectoryPoint>& points) {
    std::vector<std::size_t> chosen{0};
    const double first = points.front().objective;
    const double last = points.back().objective;
    for (const double fraction : {0.5, 0.9}) {
        const double target = first - fraction * (first - last);
        for (std::size_t index = 0; index < points.size(); ++index) {
            if (points[index].objective <= target) {
                if (index != chosen.back()) {
                    chosen.push_back(index);
                }
                break;
            }
        }
    }
    if (chosen.back() != points.size() - 1) {
        chosen.push_back(points.size() - 1);
    }
    return chosen;
}

IlsSeries runIls(LocalSearchMethods& methods, const TSPSolver& solver, const Perturbation& perturbation,
                 double time_limit_ms, unsigned int seed, unsigned int instance_code, unsigned int stream,
                 int node_count) {
    IlsSeries series;
    series.perturbation = perturbation;
    for (int run = 0; run < kRuns; ++run) {
        std::mt19937 rng = makeRng(seed, instance_code, stream, run);
        const IlsRun result = methods.iterated(time_limit_ms, perturbation, rng);
        checkResult(result.best, solver, node_count, "ILS (" + perturbation.id + ")");
        series.space.addSolution(result.best);
        series.ms.push_back(result.ms);
        series.local_searches.push_back(static_cast<double>(result.local_searches));
        series.improvements.push_back(static_cast<double>(result.improvements));
        series.runs.push_back(result);
    }
    return series;
}

void runInstance(const std::string& instance_name, const Options& options, const fs::path& lab_dir) {
    const std::string data_path = findDataFile(instance_name, options.data_dir);
    const std::vector<Node> nodes = loadInstance(data_path);
    const DistanceMatrix distances(nodes);
    const std::vector<int> costs = nodeCosts(nodes);
    const int node_count = static_cast<int>(nodes.size());
    const TSPSolver solver(distances, costs, 1);  // random solutions and the local-optimum check
    MoveListSearch local_search(distances, costs);
    LocalSearchMethods methods(solver, local_search, node_count);
    const unsigned int instance_code = instance_name == "TSPB" ? 0xB00BU : 0xA11AU;

    std::cout << "=== " << instance_name << " ===\n"
              << "Loaded " << node_count << " nodes from " << data_path << "; " << solver.targetCount()
              << " selected; " << kRuns << " runs of MSLS (" << kMslsIterations << " local searches each) and of ILS\n";

    // MSLS: its average running time becomes the time limit of ILS.
    SolutionSpace msls_space;
    std::vector<double> msls_ms;
    std::vector<double> local_optima;
    std::vector<double> local_search_ms;
    std::vector<std::vector<TrajectoryPoint>> msls_trajectories;
    for (int run = 0; run < kRuns; ++run) {
        std::mt19937 rng = makeRng(options.seed, instance_code, 1, run);
        const MslsRun result = methods.multipleStart(kMslsIterations, rng);
        checkResult(result.best, solver, node_count, "MSLS");
        msls_space.addSolution(result.best);
        msls_ms.push_back(result.ms);
        msls_trajectories.push_back(result.trajectory);
        local_optima.insert(local_optima.end(), result.local_optima.begin(), result.local_optima.end());
        local_search_ms.insert(local_search_ms.end(), result.local_search_ms.begin(), result.local_search_ms.end());
    }
    const double time_limit_ms = average(msls_ms);
    std::cout << "  MSLS done; ILS time limit (average MSLS time): " << time_limit_ms << " ms\n";

    IlsSeries ils = runIls(methods, solver, chosenPerturbation(), time_limit_ms, options.seed, instance_code, 2,
                           node_count);
    std::cout << "  ILS done\n";

    const fs::path evaluation_dir = lab_dir / "evaluation";
    const fs::path results_dir = evaluation_dir / "results";
    const fs::path plots_dir = evaluation_dir / "plots";
    fs::create_directories(results_dir);
    fs::create_directories(plots_dir);

    std::ofstream stats_out = openOutput(evaluation_dir / (instance_name + "_stats.csv"));
    stats_out << "method_name,min,max,avg,sd\n" << std::fixed << std::setprecision(2);
    std::ofstream times_out = openOutput(evaluation_dir / (instance_name + "_times.csv"));
    times_out << "method_name,average_ms,minimum_ms,maximum_ms,time_limit_ms\n" << std::fixed << std::setprecision(4);
    std::ofstream runs_out = openOutput(evaluation_dir / (instance_name + "_ls_runs.csv"));
    runs_out << "method_name,average,minimum,maximum,improvements_average\n" << std::fixed << std::setprecision(2);

    // A single run of the basic local search from a random solution (all runs inside MSLS).
    const Stats single = statsOf(local_optima);
    const Stats single_ms = statsOf(local_search_ms);
    stats_out << "local_search," << single.min << ',' << single.max << ',' << single.avg << ',' << single.sd << '\n';
    times_out << "local_search," << average(local_search_ms) << ',' << single_ms.min << ',' << single_ms.max << ",\n";

    const Stats msls = msls_space.stats();
    const Stats msls_time = statsOf(msls_ms);
    stats_out << "msls," << msls.min << ',' << msls.max << ',' << msls.avg << ',' << msls.sd << '\n';
    times_out << "msls," << average(msls_ms) << ',' << msls_time.min << ',' << msls_time.max << ",\n";
    runs_out << "msls," << kMslsIterations << ',' << kMslsIterations << ',' << kMslsIterations << ",\n";

    const Stats ils_stats = ils.space.stats();
    const Stats ils_time = statsOf(ils.ms);
    const Stats ils_runs = statsOf(ils.local_searches);
    stats_out << "ils," << ils_stats.min << ',' << ils_stats.max << ',' << ils_stats.avg << ',' << ils_stats.sd << '\n';
    times_out << "ils," << average(ils.ms) << ',' << ils_time.min << ',' << ils_time.max << ',' << time_limit_ms << '\n';
    runs_out << "ils," << average(ils.local_searches) << ',' << ils_runs.min << ',' << ils_runs.max << ','
             << average(ils.improvements) << '\n';

    std::cout << "*** Single local search (" << local_optima.size() << " runs) ***\nMin: " << single.min
              << "  Max: " << single.max << "  Avg: " << single.avg << "  time " << average(local_search_ms) << " ms\n"
              << "*** MSLS ***\nMin: " << msls.min << "  Max: " << msls.max << "  Avg: " << msls.avg
              << "  time " << average(msls_ms) << " ms\nBest route: ";
    printRoute(msls_space.bestSolution().route);
    std::cout << "*** ILS (" << ils.perturbation.label << ") ***\nMin: " << ils_stats.min << "  Max: " << ils_stats.max
              << "  Avg: " << ils_stats.avg << "  time " << average(ils.ms) << " ms  local searches "
              << average(ils.local_searches) << " (" << ils_runs.min << " - " << ils_runs.max << ")\nBest route: ";
    printRoute(ils.space.bestSolution().route);

    // Every run of MSLS and ILS.
    std::ofstream per_run_out = openOutput(evaluation_dir / (instance_name + "_runs.csv"));
    per_run_out << "method_name,run,objective,time_ms,local_searches,improvements\n" << std::fixed
                << std::setprecision(4);
    for (int run = 0; run < kRuns; ++run) {
        const std::size_t index = static_cast<std::size_t>(run);
        per_run_out << "msls," << run << ',' << msls_space.solutions()[index].total_cost << ',' << msls_ms[index] << ','
                    << kMslsIterations << ",\n";
    }
    for (int run = 0; run < kRuns; ++run) {
        const std::size_t index = static_cast<std::size_t>(run);
        per_run_out << "ils," << run << ',' << ils.space.solutions()[index].total_cost << ',' << ils.ms[index] << ','
                    << static_cast<long long>(ils.local_searches[index]) << ','
                    << static_cast<long long>(ils.improvements[index]) << '\n';
    }

    const auto write_solutions = [&](const SolutionSpace& space, const std::string& id, const std::string& label) {
        space.writeBestSolutionCsv((results_dir / (instance_name + "_" + id + ".csv")).string());
        space.writeWorstSolutionCsv((results_dir / (instance_name + "_" + id + "_worst.csv")).string());
        space.writeSvg((plots_dir / (instance_name + "_" + id + ".svg")).string(), nodes, instance_name + " " + label);
        space.writeWorstSvg((plots_dir / (instance_name + "_" + id + "_worst.svg")).string(), nodes,
                            instance_name + " " + label + " (worst)");
    };
    write_solutions(msls_space, "msls", "MSLS");
    write_solutions(ils.space, "ils", "ILS");

    // Trajectory of the best solution of every run: the first local optimum, every improvement (MSLS: of
    // the best local optimum found so far; ILS: every accepted solution) and the end of the run.
    std::ofstream trajectory_out = openOutput(evaluation_dir / (instance_name + "_trajectory.csv"));
    trajectory_out << "method_name,run,event,ms,local_searches,objective\n" << std::fixed << std::setprecision(4);
    const auto write_trajectory = [&](const std::string& method, int run, const std::vector<TrajectoryPoint>& points,
                                      double end_ms, long long end_local_searches) {
        for (std::size_t index = 0; index < points.size(); ++index) {
            trajectory_out << method << ',' << run << ',' << (index == 0 ? "start" : "improvement") << ','
                           << points[index].ms << ',' << points[index].local_searches << ','
                           << points[index].objective << '\n';
        }
        trajectory_out << method << ',' << run << ",end," << end_ms << ',' << end_local_searches << ','
                       << points.back().objective << '\n';
    };
    for (int run = 0; run < kRuns; ++run) {
        const std::size_t index = static_cast<std::size_t>(run);
        write_trajectory("msls", run, msls_trajectories[index], msls_ms[index], kMslsIterations);
    }
    for (int run = 0; run < kRuns; ++run) {
        const IlsRun& result = ils.runs[static_cast<std::size_t>(run)];
        write_trajectory("ils", run, result.trajectory, result.ms, result.local_searches);
    }

    // Snapshots of the trajectory of the run that found the best ILS solution.
    std::size_t best_run = 0;
    for (std::size_t run = 1; run < ils.runs.size(); ++run) {
        if (ils.runs[run].best.total_cost < ils.runs[best_run].best.total_cost) {
            best_run = run;
        }
    }
    const IlsRun& best = ils.runs[best_run];
    std::ofstream snapshots_out = openOutput(evaluation_dir / (instance_name + "_trajectory_snapshots.csv"));
    snapshots_out << "snapshot,run,point,ms,local_searches,objective\n" << std::fixed << std::setprecision(4);
    const std::vector<std::size_t> chosen = snapshotPoints(best.trajectory);
    for (std::size_t snapshot = 0; snapshot < chosen.size(); ++snapshot) {
        const TrajectoryPoint& point = best.trajectory[chosen[snapshot]];
        const Result solution{best.trajectory_routes[chosen[snapshot]], point.objective};
        checkResult(solution, solver, node_count, "ILS trajectory");
        SolutionSpace space;
        space.addSolution(solution);
        const std::string id = "ils_trajectory_" + std::to_string(snapshot + 1);
        space.writeBestSolutionCsv((results_dir / (instance_name + "_" + id + ".csv")).string());
        space.writeSvg((plots_dir / (instance_name + "_" + id + ".svg")).string(), nodes,
                       instance_name + " ILS trajectory, snapshot " + std::to_string(snapshot + 1));
        snapshots_out << snapshot + 1 << ',' << best_run << ',' << chosen[snapshot] << ',' << point.ms << ','
                      << point.local_searches << ',' << point.objective << '\n';
    }

    if (!options.perturbation_experiment) {
        return;
    }
    // Additional experiment: ILS with other perturbations, the same time limit and 20 runs each.
    std::ofstream perturbations_out = openOutput(evaluation_dir / (instance_name + "_perturbations.csv"));
    perturbations_out << "perturbation,label,double_bridges,segment_length,random_moves,min,max,avg,sd,"
                         "ls_runs_average,ls_runs_minimum,ls_runs_maximum\n"
                      << std::fixed << std::setprecision(2);
    unsigned int stream = 3;
    for (const Perturbation& perturbation : comparedPerturbations()) {
        IlsSeries series = perturbation.id == ils.perturbation.id
                               ? ils
                               : runIls(methods, solver, perturbation, time_limit_ms, options.seed, instance_code,
                                        stream++, node_count);
        const Stats stats = series.space.stats();
        const Stats runs = statsOf(series.local_searches);
        perturbations_out << perturbation.id << ',' << perturbation.label << ',' << perturbation.double_bridges << ','
                          << perturbation.segment_length << ',' << perturbation.random_moves << ',' << stats.min << ','
                          << stats.max << ',' << stats.avg << ',' << stats.sd << ',' << average(series.local_searches)
                          << ',' << runs.min << ',' << runs.max << '\n';
        std::cout << "  perturbation " << perturbation.id << ": avg " << stats.avg << " (" << stats.min << " - "
                  << stats.max << "), local searches " << average(series.local_searches) << '\n';
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
        } else if (argument == "--perturbation-experiment") {
            options.perturbation_experiment = true;
        } else if (argument == "--help") {
            std::cout << "Usage: lab06 [--data-dir DIR] [--seed N] [--perturbation-experiment] [TSPA] [TSPB]\n";
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
