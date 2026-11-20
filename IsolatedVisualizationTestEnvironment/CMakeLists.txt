cmake_minimum_required(VERSION 3.24)
project(CrockerVisualizationBenchmarks LANGUAGES CXX)

option(BENCHMARK_ENABLE_CUDA "Build the CUDA backend" ON)
if(BENCHMARK_ENABLE_CUDA)
    enable_language(CUDA)
    find_package(CUDAToolkit REQUIRED)
endif()

add_subdirectory(features/bar_plot)
