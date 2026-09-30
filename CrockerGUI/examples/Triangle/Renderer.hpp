#pragma once

#include "Buffers/VAO.hpp"
#include "Buffers/VBO.hpp"
#include "Camera.hpp"
#include "Shader/Shader.hpp"

class Renderer {
public:
    static void LoadOpenGL(GLADloadproc loadProcedure);

    Renderer(const char* vertexPath, const char* fragmentPath);

    void Initialize(const char* pathToData = nullptr);
    void Render(int width, int height);
    void Shutdown();

    Camera& GetCamera();

private:
    Shader shader;
    VBO vbo;
    VAO vao;
    Camera camera;
    GLsizei vertexCount = 0;
};
