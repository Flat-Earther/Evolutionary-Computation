#pragma once

#include "node.hpp"

#include <cstddef>
#include <vector>

// Dense n x n matrix of mathematically rounded Euclidean distances, stored row-major in a
// single contiguous buffer so that a row can be scanned without pointer chasing.
class DistanceMatrix {
public:
    explicit DistanceMatrix(const std::vector<Node>& nodes);

    int size() const { return size_; }
    int operator()(int from, int to) const { return row(from)[to]; }
    const int* row(int from) const { return data_.data() + static_cast<std::ptrdiff_t>(from) * size_; }

private:
    int size_ = 0;
    std::vector<int> data_;
};
