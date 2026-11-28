cmake_minimum_required(VERSION 3.16)
project(lab06_msls_and_ils LANGUAGES CXX)

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
set(LAB06_ARCH "x86-64-v2" CACHE STRING "Value passed to -march; empty keeps the compiler default")

add_executable(lab06
    src/main.cpp
    src/distance_matrix.cpp
    src/instance.cpp
    src/solution_space.cpp
    src/tsp_solver.cpp
    src/lm_search.cpp
    src/msls_ils.cpp
)

if(MSVC)
    target_compile_options(lab06 PRIVATE /W4)
else()
    target_compile_options(lab06 PRIVATE -Wall -Wextra -Wpedantic)
    if(LAB06_ARCH)
        include(CheckCXXCompilerFlag)
        string(MAKE_C_IDENTIFIER "LAB06_HAS_MARCH_${LAB06_ARCH}" arch_check)
        check_cxx_compiler_flag("-march=${LAB06_ARCH}" ${arch_check})
        if(${arch_check})
            target_compile_options(lab06 PRIVATE "-march=${LAB06_ARCH}")
        else()
            message(WARNING "The compiler does not accept -march=${LAB06_ARCH}; building without it")
        endif()
    endif()
endif()
