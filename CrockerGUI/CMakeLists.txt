cmake_minimum_required(VERSION 3.22)

if(POLICY CMP0141)
    cmake_policy(SET CMP0141 NEW)
endif()
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "$<$<CONFIG:Debug,RelWithDebInfo>:Embedded>")

project(CrockerGUI LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_CXX_SCAN_FOR_MODULES OFF)

option(CROCKER_BUILD_PYTHON "Build the Python extension" ON)
option(CROCKER_BUILD_OPENGL_TEST "Build the standalone OpenGL 4.6 smoke test" OFF)

find_package(OpenGL REQUIRED)

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/external/libzmq/CMakeLists.txt")
    set(BUILD_SHARED OFF CACHE BOOL "Build ZeroMQ shared library" FORCE)
    set(BUILD_STATIC ON CACHE BOOL "Build ZeroMQ static library" FORCE)
    set(BUILD_TESTS OFF CACHE BOOL "Build ZeroMQ tests" FORCE)
    set(WITH_DOCS OFF CACHE BOOL "Build ZeroMQ docs" FORCE)
    set(WITH_PERF_TOOL OFF CACHE BOOL "Build ZeroMQ perf tools" FORCE)

    add_subdirectory(external/libzmq EXCLUDE_FROM_ALL)
endif()

if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/external/cppzmq/CMakeLists.txt")
    set(CPPZMQ_BUILD_TESTS OFF CACHE BOOL "Build cppzmq tests" FORCE)

    add_subdirectory(external/cppzmq EXCLUDE_FROM_ALL)
endif()

add_library(crocker_engine STATIC
    source/Engine/Engine.cpp
    source/Engine/Render/Camera.cpp
    source/Engine/Render/Renderer.cpp
    source/Engine/Render/Buffers/VAO.cpp
    source/Engine/Render/Buffers/VBO.cpp
    source/Engine/Render/Shader/Shader.cpp
    source/Engine/Viz/Charts/LineChart/LineChart.cpp
    source/Engine/Viz/Charts/TimeSeriesChart/TimeSeriesChart.cpp
    source/Engine/Viz/Charts/ScatterPlot/ScatterPlot.cpp
    source/Engine/Viz/Charts/HistogramChart/HistogramChart.cpp
    source/Engine/Viz/Charts/SpectrumChart/SpectrumChart.cpp
    source/Engine/Viz/Charts/HeatmapChart/HeatmapChart.cpp
    source/Engine/Viz/Charts/AlarmTimelineChart/AlarmTimelineChart.cpp
    source/Engine/Viz/Charts/BulletChart/BulletChart.cpp
    source/Engine/Viz/Charts/StarPlot/StarPlot.cpp
    source/Engine/Viz/Charts/BarChart/BarChart.cpp
    source/Controls/Network/ZMQProtocol.cpp
    source/Controls/Network/ZMQReceiver.cpp
    source/Controls/Network/ZMQSender.cpp
    source/Controls/Network/ZMQServer.cpp
    source/Controls/Transport/SimulatorTransport.cpp
    source/Controls/Transport/ServerTransport.cpp
    source/Controls/Service/ControlService.cpp
    external/glad/src/glad.c
)

set_target_properties(crocker_engine PROPERTIES POSITION_INDEPENDENT_CODE ON)

target_include_directories(crocker_engine
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    SYSTEM PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/external/glad/include
        ${CMAKE_CURRENT_SOURCE_DIR}/external/glm
        ${CMAKE_CURRENT_SOURCE_DIR}/external
)

target_link_libraries(crocker_engine PUBLIC OpenGL::GL)

if(TARGET cppzmq-static)
    target_link_libraries(crocker_engine PUBLIC cppzmq-static)
endif()

if(MSVC)
    target_compile_options(crocker_engine PRIVATE /W4 /permissive-)
else()
    target_compile_options(crocker_engine PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(CROCKER_BUILD_PYTHON)
    find_package(Python REQUIRED COMPONENTS Interpreter Development.Module)

    execute_process(
        COMMAND ${Python_EXECUTABLE} -m pybind11 --cmakedir
        OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
        RESULT_VARIABLE PYBIND11_CMAKE_RESULT
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_QUIET
    )

    if(PYBIND11_CMAKE_RESULT EQUAL 0 AND EXISTS "${PYBIND11_CMAKE_DIR}/pybind11Config.cmake")
        set(pybind11_DIR "${PYBIND11_CMAKE_DIR}" CACHE PATH "pybind11 CMake package directory" FORCE)
    else()
        message(FATAL_ERROR
            "pybind11 was not found for Python executable: ${Python_EXECUTABLE}\n"
            "Install it into that environment with:\n"
            "  ${Python_EXECUTABLE} -m pip install pybind11"
        )
    endif()

    find_package(pybind11 CONFIG REQUIRED)

    pybind11_add_module(CycloViz
        source/Bindings/Bindings.cpp
        source/Bindings/EngineBindings.cpp
        source/Bindings/TransportBindings.cpp
        source/Bindings/ControlServiceBindings.cpp
    )
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
