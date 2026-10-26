#include "distance_matrix.hpp"

#include <cmath>
#include <stdexcept>

DistanceMatrix::DistanceMatrix(const std::vector<Node>& nodes) {
    const int n = static_cast<int>(nodes.size());
    if (n == 0) {
        throw std::invalid_argument("instance must contain at least one node");
    }

    matrix_.assign(n, std::vector<int>(n, 0));
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            if (i == j) {
                continue;
            }
            const double dx = static_cast<double>(nodes[i].x) - static_cast<double>(nodes[j].x);
            const double dy = static_cast<double>(nodes[i].y) - static_cast<double>(nodes[j].y);
            matrix_[i][j] = static_cast<int>(std::llround(std::sqrt(dx * dx + dy * dy)));
        }
    }
}
