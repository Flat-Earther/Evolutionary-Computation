#include "solution_space.hpp"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>

namespace {

double roundToTwoDecimals(double value) {
    return std::round(value * 100.0) / 100.0;
}

std::string colorForCost(int cost, int min_cost, int max_cost) {
    double t = 0.0;
    if (max_cost > min_cost) {
        t = static_cast<double>(cost - min_cost) / static_cast<double>(max_cost - min_cost);
    }
    const int r = static_cast<int>(std::round(255 * t));
    const int g = static_cast<int>(std::round(80 * (1.0 - t)));
    const int b = static_cast<int>(std::round(255 * (1.0 - t)));
    std::ostringstream out;
    out << "rgb(" << r << "," << g << "," << b << ")";
    return out.str();
}

}  // namespace

void SolutionSpace::addSolution(const Result& result) {
    solutions_.push_back(result);
}

double SolutionSpace::min() const {
    if (solutions_.empty()) {
        throw std::runtime_error("no solutions recorded");
    }
    double value = solutions_.front().total_cost;
    for (const auto& sol : solutions_) {
        value = std::min(value, static_cast<double>(sol.total_cost));
    }
    return value;
}

double SolutionSpace::max() const {
    if (solutions_.empty()) {
        throw std::runtime_error("no solutions recorded");
    }
    double value = solutions_.front().total_cost;
    for (const auto& sol : solutions_) {
        value = std::max(value, static_cast<double>(sol.total_cost));
    }
    return value;
}

double SolutionSpace::avg() const {
    if (solutions_.empty()) {
        throw std::runtime_error("no solutions recorded");
    }
    double sum = 0.0;
    for (const auto& sol : solutions_) {
        sum += sol.total_cost;
    }
    return sum / static_cast<double>(solutions_.size());
}

double SolutionSpace::sd() const {
    const double mean = avg();
    double sum = 0.0;
    for (const auto& sol : solutions_) {
        const double diff = static_cast<double>(sol.total_cost) - mean;
        sum += diff * diff;
    }
    return std::sqrt(sum / static_cast<double>(solutions_.size()));
}

Stats SolutionSpace::stats() const {
    return {min(), max(), roundToTwoDecimals(avg()), roundToTwoDecimals(sd())};
}

const Result& SolutionSpace::bestSolution() const {
    if (solutions_.empty()) {
        throw std::runtime_error("no solutions recorded");
    }
    std::size_t best = 0;
    for (std::size_t i = 1; i < solutions_.size(); ++i) {
        if (solutions_[i].total_cost <= solutions_[best].total_cost) {
            best = i;
        }
    }
    return solutions_[best];
}

void SolutionSpace::writeBestSolutionCsv(const std::string& path) const {
    const auto& best = bestSolution();
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path);
    }
    for (int node : best.route) {
        out << node << "\n";
    }
}

void SolutionSpace::writeSvg(const std::string& path, const std::vector<Node>& nodes, const std::string& title) const {
    if (nodes.empty()) {
        throw std::runtime_error("no nodes to visualize");
    }

    int min_x = nodes.front().x;
    int max_x = nodes.front().x;
    int min_y = nodes.front().y;
    int max_y = nodes.front().y;
    int min_cost = nodes.front().cost;
    int max_cost = nodes.front().cost;
    for (const auto& node : nodes) {
        min_x = std::min(min_x, node.x);
        max_x = std::max(max_x, node.x);
        min_y = std::min(min_y, node.y);
        max_y = std::max(max_y, node.y);
        min_cost = std::min(min_cost, node.cost);
        max_cost = std::max(max_cost, node.cost);
    }

    constexpr int padding = 40;
    constexpr int width = 900;
    constexpr int height = 900;
    const double span_x = std::max(1, max_x - min_x);
    const double span_y = std::max(1, max_y - min_y);

    auto map_x = [&](int x) {
        return padding + (static_cast<double>(x - min_x) / span_x) * (width - 2 * padding);
    };
    auto map_y = [&](int y) {
        return height - padding - (static_cast<double>(y - min_y) / span_y) * (height - 2 * padding);
    };

    const auto& best = bestSolution();
    std::ofstream out(path);
    if (!out) {
        throw std::runtime_error("cannot write " + path);
    }

    out << std::fixed << std::setprecision(2);
    out << "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" << width << "\" height=\"" << height
        << "\" viewBox=\"0 0 " << width << " " << height << "\">\n";
    out << "<rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n";
    out << "<text x=\"" << padding << "\" y=\"24\" font-family=\"sans-serif\" font-size=\"16\">" << title
        << " | objective=" << best.total_cost << "</text>\n";

    if (best.route.size() >= 2) {
        out << "<polyline fill=\"none\" stroke=\"#333333\" stroke-width=\"2\" points=\"";
        for (int index : best.route) {
            out << map_x(nodes[index].x) << "," << map_y(nodes[index].y) << " ";
        }
        out << "\"/>\n";
    }

    for (std::size_t i = 0; i < nodes.size(); ++i) {
        const auto& node = nodes[i];
        const double radius = 4.0 + 8.0 * (max_cost > min_cost
                                               ? static_cast<double>(node.cost - min_cost) / (max_cost - min_cost)
                                               : 0.0);
        out << "<circle cx=\"" << map_x(node.x) << "\" cy=\"" << map_y(node.y) << "\" r=\"" << radius
            << "\" fill=\"" << colorForCost(node.cost, min_cost, max_cost)
            << "\" stroke=\"#222\" stroke-width=\"0.8\"/>\n";
    }

    out << "</svg>\n";
}
