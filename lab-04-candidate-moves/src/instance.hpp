#pragma once

#include "node.hpp"

#include <string>
#include <vector>

std::vector<Node> loadInstance(const std::string& path);
std::string findDataFile(const std::string& instance_name, const std::string& data_dir);
std::vector<int> nodeCosts(const std::vector<Node>& nodes);
