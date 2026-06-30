cmake_minimum_required(VERSION 3.22)

project(CrockerGUI LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(CROCKER_BUILD_PYTHON "Build the Python extension" ON)
option(CROCKER_BUILD_OPENGL_TEST "Build the standalone OpenGL 4.6 smoke test" OFF)

find_package(OpenGL REQUIRED)

add_library(crocker_engine STATIC
    source/Engine/Engine.cpp
    source/Engine/Render/Camera.cpp
    source/Engine/Render/Renderer.cpp
    source/Engine/Render/Buffers/VAO.cpp
    source/Engine/Render/Buffers/VBO.cpp
    source/Engine/Render/Shader/Shader.cpp
    source/Engine/Viz/Charts/LineChart/LineChart.cpp
    source/Engine/Viz/Charts/BarChart/BarChart.cpp
    external/glad/src/glad.c
)

set_target_properties(crocker_engine PROPERTIES POSITION_INDEPENDENT_CODE ON)

target_include_directories(crocker_engine
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    SYSTEM PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/external/glad/include
        ${CMAKE_CURRENT_SOURCE_DIR}/external
)

target_link_libraries(crocker_engine PUBLIC OpenGL::GL)

if(MSVC)
    target_compile_options(crocker_engine PRIVATE /W4 /permissive-)
else()
    target_compile_options(crocker_engine PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(CROCKER_BUILD_PYTHON)
    find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)
    find_package(pybind11 CONFIG REQUIRED)

    pybind11_add_module(CycloViz source/Bindings.cpp)
    target_link_libraries(CycloViz PRIVATE crocker_engine)

    set_target_properties(CycloViz PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    )
endif()

if(CROCKER_BUILD_OPENGL_TEST)
    # GLFW is a debug/test-only dependency.  Keep it out of the engine and
    # Python module unless the standalone OpenGL diagnostic is requested.
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/external/GLFW/CMakeLists.txt")
        add_subdirectory(external/GLFW EXCLUDE_FROM_ALL)
    else()
        find_package(glfw3 CONFIG REQUIRED)
    endif()

    add_executable(CrockerOpenGLTest tests/OpenGLTest.cpp)
    target_link_libraries(CrockerOpenGLTest PRIVATE crocker_engine glfw)

    add_custom_command(TARGET CrockerOpenGLTest POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/shaders
            $<TARGET_FILE_DIR:CrockerOpenGLTest>/shaders
    )
endif()
