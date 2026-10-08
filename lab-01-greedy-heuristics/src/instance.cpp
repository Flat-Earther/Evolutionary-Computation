#include "instance.hpp"

#include <algorithm>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <vector>

std::vector<Node> loadInstance(const std::string& path) {
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("cannot open instance file: " + path);
    }

    std::vector<Node> nodes;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) {
            continue;
        }
        std::replace(line.begin(), line.end(), ',', ';');
        std::istringstream ss(line);
        std::string xs, ys, cs;
        if (!std::getline(ss, xs, ';') || !std::getline(ss, ys, ';') || !std::getline(ss, cs, ';')) {
            continue;
        }
        nodes.push_back({std::stoi(xs), std::stoi(ys), std::stoi(cs)});
    }
    if (nodes.empty()) {
        throw std::runtime_error("instance is empty: " + path);
    }
    return nodes;
}

std::string findDataFile(const std::string& instance_name, const std::string& data_dir) {
    const std::vector<std::string> candidates = {
        data_dir.empty() ? "" : data_dir + "/" + instance_name + ".csv",
        "../problem-description/data/example/" + instance_name + ".csv",
        "../../problem-description/data/example/" + instance_name + ".csv",
        "problem-description/data/example/" + instance_name + ".csv",
        "../data/" + instance_name + ".csv",
        "../../data/" + instance_name + ".csv",
        "data/" + instance_name + ".csv",
    };

    for (const auto& path : candidates) {
        if (path.empty()) {
            continue;
        }
        std::ifstream in(path);
        if (in) {
            return path;
        }
    }
    throw std::runtime_error("could not find instance file for " + instance_name);
}
