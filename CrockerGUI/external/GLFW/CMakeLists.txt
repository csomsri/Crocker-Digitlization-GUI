cmake_minimum_required(VERSION 3.22)

# Minimal GLFW build used by CrockerOpenGLTest.  The vendored source snapshot
# contains the public headers and implementation, but not GLFW's top-level
# build files.
if(NOT WIN32)
    message(FATAL_ERROR
        "The minimal vendored GLFW build currently supports Windows only; "
        "use an installed glfw3 package on this platform."
    )
endif()

find_package(Threads REQUIRED)

add_library(glfw STATIC
    src/context.c
    src/init.c
    src/input.c
    src/monitor.c
    src/platform.c
    src/vulkan.c
    src/window.c
    src/egl_context.c
    src/osmesa_context.c
    src/null_init.c
    src/null_monitor.c
    src/null_window.c
    src/null_joystick.c
    src/win32_init.c
    src/win32_joystick.c
    src/win32_monitor.c
    src/win32_window.c
    src/win32_module.c
    src/win32_time.c
    src/win32_thread.c
    src/wgl_context.c
)

target_compile_definitions(glfw PRIVATE _GLFW_WIN32)
target_include_directories(glfw
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src
)
target_link_libraries(glfw PRIVATE Threads::Threads)
set_target_properties(glfw PROPERTIES FOLDER "Debug dependencies")
