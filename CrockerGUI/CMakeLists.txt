cmake_minimum_required(VERSION 3.24)

project(CrockerGUI LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)

option(BUILD_GLFW_TEST "Build standalone GLFW debug executable" ON)

find_package(OpenGL REQUIRED)
find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)

# -----------------------------
# PySide6 Python module backend
# -----------------------------
pybind11_add_module(viz_engine
    src/Bindings.cpp
    src/Engine.cpp
    src/Renderer.cpp
    src/Shader.cpp
    src/CudaInteropBuffer.cpp
    src/kernels.cu
    external/glad/src/gl.c
)

target_include_directories(viz_engine PRIVATE
    ${CMAKE_SOURCE_DIR}/include
    ${CMAKE_SOURCE_DIR}/external/glad/include
    ${CMAKE_SOURCE_DIR}/external/glm
)

target_link_libraries(viz_engine PRIVATE
    OpenGL::GL
)

set_target_properties(viz_engine PROPERTIES
    CUDA_SEPARABLE_COMPILATION ON
)

# Put built Python module near main.py
set_target_properties(viz_engine PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}
)

# -----------------------------
# Optional GLFW debug executable
# -----------------------------
if(BUILD_GLFW_TEST)
    add_subdirectory(external/glfw)

    add_executable(CrockerGUITest
        tests/glfw_main.cpp
        src/Engine.cpp
        src/Renderer.cpp
        src/Shader.cpp
        src/CudaInteropBuffer.cpp
        src/kernels.cu
        external/glad/src/gl.c
    )

    target_include_directories(CrockerGUITest PRIVATE
        ${CMAKE_SOURCE_DIR}/include
        ${CMAKE_SOURCE_DIR}/external/glad/include
        ${CMAKE_SOURCE_DIR}/external/glm
        ${CMAKE_SOURCE_DIR}/external/glfw/include
    )

    target_link_libraries(CrockerGUITest PRIVATE
        OpenGL::GL
        glfw
    )

    set_target_properties(CrockerGUITest PROPERTIES
        CUDA_SEPARABLE_COMPILATION ON
    )
endif()