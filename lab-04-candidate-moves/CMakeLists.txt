cmake_minimum_required(VERSION 3.16)
project(lab04_candidate_moves LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# The experiment reports running times, so never fall back to an unoptimised build:
# without a build type, single-configuration generators compile without -O flags.
if(NOT CMAKE_CONFIGURATION_TYPES AND NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

# Instruction-set level passed to -march (GCC/Clang). x86-64-v2 (SSE4.2) runs on practically
# every x86-64 CPU of the last decade; x86-64-v3 (AVX2) makes the full-neighbourhood baseline
# faster still but needs an AVX2 CPU. An empty value keeps the compiler default.
set(LAB04_ARCH "x86-64-v2" CACHE STRING "Value passed to -march; empty keeps the compiler default")

add_executable(lab04
    src/main.cpp
    src/distance_matrix.cpp
    src/instance.cpp
    src/solution_space.cpp
    src/tsp_solver.cpp
)

if(MSVC)
    target_compile_options(lab04 PRIVATE /W4)
else()
    target_compile_options(lab04 PRIVATE -Wall -Wextra -Wpedantic)
    if(LAB04_ARCH)
        include(CheckCXXCompilerFlag)
        string(MAKE_C_IDENTIFIER "LAB04_HAS_MARCH_${LAB04_ARCH}" arch_check)
        check_cxx_compiler_flag("-march=${LAB04_ARCH}" ${arch_check})
        if(${arch_check})
            target_compile_options(lab04 PRIVATE "-march=${LAB04_ARCH}")
        else()
            message(WARNING "The compiler does not accept -march=${LAB04_ARCH}; building without it")
        endif()
    endif()
endif()
