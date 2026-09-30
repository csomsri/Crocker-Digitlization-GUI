#pragma once

#include <glad/glad.h>

class VBO {
public:
    VBO();
    ~VBO();

    VBO(const VBO&) = delete;
    VBO& operator=(const VBO&) = delete;
    VBO(VBO&& other) noexcept;
    VBO& operator=(VBO&& other) noexcept;

    void Bind() const;
    static void Unbind();
    void SetData(GLsizeiptr size, const void* data, GLenum usage = GL_STATIC_DRAW) const;

    GLuint GetID() const;

private:
    GLuint ID = 0;
};
