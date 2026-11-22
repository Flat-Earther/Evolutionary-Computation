#include "distance_matrix.hpp"

#include <cmath>
#include <stdexcept>

DistanceMatrix::DistanceMatrix(const std::vector<Node>& nodes) : size_(static_cast<int>(nodes.size())) {
    if (size_ == 0) {
        throw std::invalid_argument("instance must contain at least one node");
    }

    data_.assign(static_cast<std::size_t>(size_) * static_cast<std::size_t>(size_), 0);
    for (int i = 0; i < size_; ++i) {
        int* out = data_.data() + static_cast<std::ptrdiff_t>(i) * size_;
        for (int j = 0; j < size_; ++j) {
            if (i == j) {
                continue;
            }
            const double dx = static_cast<double>(nodes[i].x) - static_cast<double>(nodes[j].x);
            const double dy = static_cast<double>(nodes[i].y) - static_cast<double>(nodes[j].y);
            out[j] = static_cast<int>(std::llround(std::sqrt(dx * dx + dy * dy)));
        }
    }
}
