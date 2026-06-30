#include "Engine/Engine/Render/Renderer.hpp"

#include <glm/gtc/matrix_transform.hpp>

#include <algorithm>
#include <stdexcept>

void Renderer::LoadOpenGL(GLADloadproc loadProcedure) {
    if (loadProcedure == nullptr || gladLoadGLLoader(loadProcedure) == 0) {
        throw std::runtime_error("Unable to load OpenGL functions");
    }
    if (GLAD_GL_VERSION_4_6 == 0) {
        throw std::runtime_error("CrockerGUI requires an OpenGL 4.6 core context");
    }
}

Renderer::Renderer(const char* vertexPath, const char* fragmentPath)
    : shader(vertexPath, fragmentPath) {}

void Renderer::Initialize(const char* pathToData) {
    (void)pathToData;

    constexpr float vertices[] = {
         0.0f,  0.5f,
        -0.5f, -0.5f,
         0.5f, -0.5f
    };

    vertexCount = 3;
    vbo.SetData(sizeof(vertices), vertices);
    vao.SetVertexBuffer(0, vbo, 0, 2 * sizeof(float));
    vao.SetAttribute(0, 2, GL_FLOAT, 0, 0);

    glEnable(GL_DEPTH_TEST);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);
}

void Renderer::Render(int width, int height) {
    const int safeWidth = std::max(width, 1);
    const int safeHeight = std::max(height, 1);

    glViewport(0, 0, safeWidth, safeHeight);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    const glm::mat4 model(1.0f);
    const glm::mat4 view = camera.GetViewMatrix();
    const glm::mat4 projection = glm::perspective(
        glm::radians(camera.GetZoom()),
        static_cast<float>(safeWidth) / static_cast<float>(safeHeight),
        0.1f,
        100.0f
    );

    shader.SetUniformMat4("model", model);
    shader.SetUniformMat4("view", view);
    shader.SetUniformMat4("projection", projection);
    shader.Use();
    vao.Bind();
    glDrawArrays(GL_TRIANGLES, 0, vertexCount);
}

void Renderer::Shutdown() {
    Shader::Unuse();
    VAO::Unbind();
    VBO::Unbind();
}

Camera& Renderer::GetCamera() {
    return camera;
}
