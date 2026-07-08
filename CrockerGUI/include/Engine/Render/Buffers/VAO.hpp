#pragma once

#include <glad/glad.h>

class VAO {
public:
    VAO();
    ~VAO();

    VAO(const VAO&) = delete;
    VAO& operator=(const VAO&) = delete;
    VAO(VAO&& other) noexcept;
    VAO& operator=(VAO&& other) noexcept;

    void Bind() const;
    static void Unbind();
    void SetVertexBuffer(GLuint binding, const class VBO& buffer, GLintptr offset, GLsizei stride) const;
    void SetAttribute(GLuint index, GLint size, GLenum type, GLuint binding, GLuint offset) const;

private:
    GLuint ID = 0;
};
