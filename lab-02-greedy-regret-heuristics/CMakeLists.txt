cmake_minimum_required(VERSION 3.16)
project(lab02_greedy_regret_heuristics LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(lab02
    src/main.cpp
    src/distance_matrix.cpp
    src/instance.cpp
    src/solution_space.cpp
    src/tsp_solver.cpp
)

if(MSVC)
    target_compile_options(lab02 PRIVATE /W4)
else()
    target_compile_options(lab02 PRIVATE -Wall -Wextra -Wpedantic)
endif()
