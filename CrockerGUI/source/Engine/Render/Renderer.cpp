#include "renderer.h"

Renderer::Renderer(const char* vertexPath, const char* fragmentPath)
    : shader(vertexPath, fragmentPath), vertexCount(0) {
}

void Renderer::Initialize(const char* pathToData) {
    (void)pathToData;

    // Simple test triangle: 3 vertices, 2 floats each (x, y)
    float vertices[] = {
         0.0f,  0.5f,
        -0.5f, -0.5f,
         0.5f, -0.5f
    };

    vertexCount = 3;

    vbo.Bind();
    vao.Bind();

    vbo.SetData(sizeof(vertices), vertices);

    // Position attribute only: 2 floats per vertex
    vao.setAttribute(0, 2, GL_FLOAT, 2 * sizeof(float), 0);
}

void Renderer::Render(int width, int height) {
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    shader.Use();

    glm::mat4 model = glm::mat4(1.0f);
    glm::mat4 view = camera.GetViewMatrix();
    glm::mat4 projection = glm::perspective(
        glm::radians(camera.GetZoom()),
        static_cast<float>(width) / static_cast<float>(height),
        0.1f,
        100.0f
    );

    shader.setUniformMat4("model", model);
    shader.setUniformMat4("view", view);
    shader.setUniformMat4("projection", projection);

    vao.Bind();
    glDrawArrays(GL_TRIANGLES, 0, vertexCount);
}

void Renderer::Shutdown() {
    vbo.Unbind();
    vao.Unbind();
}

Renderer::~Renderer() {
    Shutdown();
}

Camera& Renderer::GetCamera() {
    return camera;
}

void Renderer::Customize() {
}