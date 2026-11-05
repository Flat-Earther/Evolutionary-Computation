#pragma once

#include "node.hpp"

#include <vector>

class DistanceMatrix {
public:
    explicit DistanceMatrix(const std::vector<Node>& nodes);

    const std::vector<std::vector<int>>& matrix() const { return matrix_; }

private:
    std::vector<std::vector<int>> matrix_;
};
