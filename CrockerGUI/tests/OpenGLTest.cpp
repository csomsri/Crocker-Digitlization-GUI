/**
    Author(s): Chotrawit Benko (L0R3ST)
    Description:
        Standalone OpenGL 4.6 render pipeline smoke test
*/

#include "Engine/Engine/Render/Renderer.hpp"

#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include <exception>
#include <filesystem>
#include <iostream>

namespace {

void OnGLFWError(int code, const char* message) {
    std::cerr << "GLFW error " << code << ": " << message << '\n';
}

void APIENTRY OnOpenGLError(
    GLenum source,
    GLenum type,
    GLuint id,
    GLenum severity,
    GLsizei length,
    const GLchar* message,
    const void* userParameter
) {
    (void)source;
    (void)type;
    (void)id;
    (void)severity;
    (void)length;
    (void)userParameter;

    std::cerr << "OpenGL: " << message << '\n';
}

} // namespace

int main(int argc, char* argv[]) {
    glfwSetErrorCallback(OnGLFWError);

    if (glfwInit() == GLFW_FALSE) {
        std::cerr << "Unable to initialize GLFW\n";
        return 1;
    }

    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 4);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 6);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
    glfwWindowHint(GLFW_OPENGL_DEBUG_CONTEXT, GLFW_TRUE);

    GLFWwindow* window = glfwCreateWindow(960, 540, "Crocker OpenGL 4.6 Test", nullptr, nullptr);
    if (window == nullptr) {
        std::cerr << "OpenGL 4.6 is unavailable. Checking the installed driver...\n";

        glfwDefaultWindowHints();
        glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
        glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
        glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
        glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);

        window = glfwCreateWindow(1, 1, "OpenGL Diagnostic", nullptr, nullptr);
        if (window != nullptr) {
            glfwMakeContextCurrent(window);
            if (gladLoadGLLoader(reinterpret_cast<GLADloadproc>(glfwGetProcAddress)) != 0) {
                std::cerr << "Available OpenGL version: " << glGetString(GL_VERSION) << '\n';
                std::cerr << "GPU renderer: " << glGetString(GL_RENDERER) << '\n';
                std::cerr << "Update the GPU driver or run outside Remote Desktop/VM software that limits OpenGL.\n";
            }
            glfwDestroyWindow(window);
        }

        glfwTerminate();
        return 1;
    }

    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

    try {
        Renderer::LoadOpenGL(reinterpret_cast<GLADloadproc>(glfwGetProcAddress));

        glEnable(GL_DEBUG_OUTPUT);
        glEnable(GL_DEBUG_OUTPUT_SYNCHRONOUS);
        glDebugMessageCallback(OnOpenGLError, nullptr);
        glClearColor(0.03f, 0.05f, 0.08f, 1.0f);

        const std::filesystem::path executableDirectory =
            argc > 0
                ? std::filesystem::absolute(argv[0]).parent_path()
                : std::filesystem::current_path();
        const std::filesystem::path shaderDirectory = executableDirectory / "shaders";
        const std::string vertexShaderPath = (shaderDirectory / "Test.vert").string();
        const std::string fragmentShaderPath = (shaderDirectory / "Test.frag").string();

        Renderer renderer(
            vertexShaderPath.c_str(),
            fragmentShaderPath.c_str()
        );
        renderer.Initialize();

        std::cout << "OpenGL: " << glGetString(GL_VERSION) << '\n';
        std::cout << "Renderer: " << glGetString(GL_RENDERER) << '\n';

        while (glfwWindowShouldClose(window) == GLFW_FALSE) {
            if (glfwGetKey(window, GLFW_KEY_ESCAPE) == GLFW_PRESS) {
                glfwSetWindowShouldClose(window, GLFW_TRUE);
            }

            int width = 0;
            int height = 0;
            glfwGetFramebufferSize(window, &width, &height);
            renderer.Render(width, height);

            glfwSwapBuffers(window);
            glfwPollEvents();
        }

        renderer.Shutdown();
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        glfwDestroyWindow(window);
        glfwTerminate();
        return 1;
    }

    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
