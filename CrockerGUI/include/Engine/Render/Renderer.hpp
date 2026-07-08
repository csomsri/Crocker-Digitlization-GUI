#pragma once

#include "Engine/Render/Buffers/VAO.hpp"
#include "Engine/Render/Buffers/VBO.hpp"
#include "Engine/Render/Camera.hpp"
#include "Engine/Render/Shader/Shader.hpp"

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
