#pragma once

#include "node.hpp"

#include <vector>

class DistanceMatrix {
public:
    explicit DistanceMatrix(const std::vector<Node>& nodes);

    const std::vector<std::vector<int>>& matrix() const { return matrix_; }
    int get(int i, int j) const { return matrix_[i][j]; }
    int size() const { return static_cast<int>(matrix_.size()); }

private:
    std::vector<std::vector<int>> matrix_;
};
