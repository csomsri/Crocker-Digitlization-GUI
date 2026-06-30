#include "Engine/Engine/Render/Buffers/VBO.hpp"

#include <utility>

VBO::VBO() {
    glCreateBuffers(1, &ID);
}

VBO::~VBO() {
    glDeleteBuffers(1, &ID);
}

VBO::VBO(VBO&& other) noexcept
    : ID(std::exchange(other.ID, 0)) {}

VBO& VBO::operator=(VBO&& other) noexcept {
    if (this != &other) {
        glDeleteBuffers(1, &ID);
        ID = std::exchange(other.ID, 0);
    }
    return *this;
}

void VBO::Bind() const {
    glBindBuffer(GL_ARRAY_BUFFER, ID);
}

void VBO::Unbind() {
    glBindBuffer(GL_ARRAY_BUFFER, 0);
}

void VBO::SetData(GLsizeiptr size, const void* data, GLenum usage) const {
    glNamedBufferData(ID, size, data, usage);
}

GLuint VBO::GetID() const {
    return ID;
}
