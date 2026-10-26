#pragma once

#include "node.hpp"
#include "tsp_solver.hpp"

#include <string>
#include <vector>

struct Stats {
    double min = 0.0;
    double max = 0.0;
    double avg = 0.0;
    double sd = 0.0;
};

class SolutionSpace {
public:
    void addSolution(const Result& result);

    double min() const;
    double max() const;
    double avg() const;
    double sd() const;
    Stats stats() const;

    const Result& bestSolution() const;
    const Result& worstSolution() const;
    void writeBestSolutionCsv(const std::string& path) const;
    void writeWorstSolutionCsv(const std::string& path) const;
    void writeSvg(const std::string& path, const std::vector<Node>& nodes, const std::string& title) const;
    void writeWorstSvg(const std::string& path, const std::vector<Node>& nodes, const std::string& title) const;

private:
    void writeSolutionSvg(const std::string& path, const std::vector<Node>& nodes, const std::string& title,
                          const Result& solution) const;

    std::vector<Result> solutions_;
};
