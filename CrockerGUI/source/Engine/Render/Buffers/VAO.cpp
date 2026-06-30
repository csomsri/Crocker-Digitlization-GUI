#include "Engine/Engine/Render/Buffers/VAO.hpp"

#include "Engine/Engine/Render/Buffers/VBO.hpp"

#include <utility>

VAO::VAO() {
    glCreateVertexArrays(1, &ID);
}

VAO::~VAO() {
    glDeleteVertexArrays(1, &ID);
}

VAO::VAO(VAO&& other) noexcept
    : ID(std::exchange(other.ID, 0)) {}

VAO& VAO::operator=(VAO&& other) noexcept {
    if (this != &other) {
        glDeleteVertexArrays(1, &ID);
        ID = std::exchange(other.ID, 0);
    }
    return *this;
}

void VAO::Bind() const {
    glBindVertexArray(ID);
}

void VAO::Unbind() {
    glBindVertexArray(0);
}

void VAO::SetVertexBuffer(GLuint binding, const VBO& buffer, GLintptr offset, GLsizei stride) const {
    glVertexArrayVertexBuffer(ID, binding, buffer.GetID(), offset, stride);
}

void VAO::SetAttribute(GLuint index, GLint size, GLenum type, GLuint binding, GLuint offset) const {
    glEnableVertexArrayAttrib(ID, index);
    glVertexArrayAttribFormat(ID, index, size, type, GL_FALSE, offset);
    glVertexArrayAttribBinding(ID, index, binding);
}
