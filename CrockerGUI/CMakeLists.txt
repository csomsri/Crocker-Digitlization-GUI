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
    source/Engine/Graphics/RenderContext.cpp
    source/Engine/Graphics/Canvas2D.cpp
    source/Engine/Graphics/OpenGL/ShaderProgram.cpp
    source/Engine/Graphics/OpenGL/StateGuard.cpp
    source/Engine/Text/FontManager.cpp
    source/Engine/Text/TextLayout.cpp
    source/Engine/Text/TextRenderer.cpp
    source/Engine/Text/Internal/FontRasterizer.cpp
    source/Engine/Text/Internal/GlyphAtlas.cpp
    source/Engine/Visualization/Plots/FieldPlots.cpp

    source/Controls/ControlSystem/NLAPID.cpp
    source/Simulation/CyclotronModel.cpp
    source/Engine/Visualization/Charts/TickFormatter.cpp
    source/Engine/Visualization/Charts/LineChart.cpp
    source/Engine/Visualization/Charts/TimeSeriesChart.cpp
    source/Engine/Visualization/Charts/ScatterPlot.cpp
    source/Engine/Visualization/Charts/HistogramChart.cpp
    source/Engine/Visualization/Charts/SpectrumChart.cpp
    source/Engine/Visualization/Charts/HeatmapChart.cpp
    source/Engine/Visualization/Charts/AlarmTimelineChart.cpp
    source/Engine/Visualization/Charts/BulletChart.cpp
    source/Engine/Visualization/Charts/StarPlot.cpp
    source/Engine/Visualization/Charts/BarChart.cpp
    source/Engine/Visualization/Gauges/MagneticFieldSpeedometer.cpp
    source/Controls/Network/ZMQProtocol.cpp
    source/Controls/Network/ZMQReceiver.cpp
    source/Controls/Network/ZMQSender.cpp
    source/Controls/Network/ZMQServer.cpp
    source/Controls/Transport/SimulatorTransport.cpp
    source/Controls/Transport/ServerTransport.cpp
    source/Controls/Service/ControlService.cpp
    source/Controls/Service/CommandGateway.cpp
    source/Controls/Sequencer/SequenceValidator.cpp
    source/Controls/Sequencer/Sequencer.cpp
    source/Controls/Sequencer/SequenceRunner.cpp
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

target_compile_definitions(crocker_engine PRIVATE
    CROCKER_ASSET_DIR="${CMAKE_CURRENT_SOURCE_DIR}/assets"
)

if(TARGET cppzmq-static)
    target_link_libraries(crocker_engine PUBLIC cppzmq-static)
endif()

include(CTest)

if(BUILD_TESTING)
    add_executable(TextLayoutTest tests/TextLayoutTest.cpp)
    target_link_libraries(TextLayoutTest PRIVATE crocker_engine)
    add_test(NAME TextLayoutTest COMMAND TextLayoutTest)

    add_executable(CyclotronModelTest
        tests/CyclotronModelTest.cpp
        source/Simulation/CyclotronModel.cpp
    )
    target_include_directories(CyclotronModelTest PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/include)
    add_test(NAME CyclotronModelTest COMMAND CyclotronModelTest)

    add_executable(ControlServicePidTrialTest
        tests/ControlServicePidTrialTest.cpp
    )
    target_link_libraries(ControlServicePidTrialTest PRIVATE crocker_engine)
    add_test(NAME ControlServicePidTrialTest COMMAND ControlServicePidTrialTest)

    foreach(sequence_test SequencerTest SequenceRunnerTest)
        add_executable(${sequence_test} tests/${sequence_test}.cpp)
        target_link_libraries(${sequence_test} PRIVATE crocker_engine)
        add_test(NAME ${sequence_test} COMMAND ${sequence_test})
    endforeach()

    add_executable(ControlServiceSequenceTest
        tests/ControlServiceSequenceTest.cpp
    )
    target_link_libraries(ControlServiceSequenceTest PRIVATE crocker_engine)
    add_test(NAME ControlServiceSequenceTest COMMAND ControlServiceSequenceTest)
endif()

if(MSVC)
    target_compile_options(crocker_engine PRIVATE /W4 /permissive-)
else()
    target_compile_options(crocker_engine PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(CROCKER_BUILD_PYTHON)
    find_package(Python 3.13...<3.14 REQUIRED COMPONENTS Interpreter Development.Module)

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
        source/Bindings/CyclotronBindings.cpp
    )
    target_link_libraries(CycloViz PRIVATE crocker_engine)

    set_target_properties(CycloViz PROPERTIES
        LIBRARY_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
        RUNTIME_OUTPUT_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    )
    foreach(config DEBUG RELEASE RELWITHDEBINFO MINSIZEREL)
        set_target_properties(CycloViz PROPERTIES
            LIBRARY_OUTPUT_DIRECTORY_${config} ${CMAKE_CURRENT_SOURCE_DIR}
            RUNTIME_OUTPUT_DIRECTORY_${config} ${CMAKE_CURRENT_SOURCE_DIR}
        )
    endforeach()
endif()

if(CROCKER_BUILD_OPENGL_TEST)
    # GLFW is a debug/test-only dependency.  Keep it out of the engine and
    # Python module unless the standalone OpenGL diagnostic is requested.
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/external/GLFW/CMakeLists.txt")
        add_subdirectory(external/GLFW EXCLUDE_FROM_ALL)
    else()
        find_package(glfw3 CONFIG REQUIRED)
    endif()

    add_executable(CrockerOpenGLTest tests/OpenGLTest.cpp
        examples/Triangle/Camera.cpp
        examples/Triangle/Renderer.cpp
        examples/Triangle/Buffers/VAO.cpp
        examples/Triangle/Buffers/VBO.cpp
        examples/Triangle/Shader/Shader.cpp
    )
    target_include_directories(CrockerOpenGLTest PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/examples/Triangle)
    target_link_libraries(CrockerOpenGLTest PRIVATE crocker_engine glfw)

    add_custom_command(TARGET CrockerOpenGLTest POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_directory
            ${CMAKE_CURRENT_SOURCE_DIR}/tests/shaders
            $<TARGET_FILE_DIR:CrockerOpenGLTest>/shaders
    )
endif()
