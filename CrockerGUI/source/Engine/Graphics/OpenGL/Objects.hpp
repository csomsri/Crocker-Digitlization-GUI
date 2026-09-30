#pragma once
#include <glad/glad.h>
#include <cstddef>
namespace crocker::engine::gl {
// Handles are released by RenderContext::Release while its context is current.
// They deliberately make no GL calls from uncontrolled static/destructor order.
struct Buffer {
    GLuint id = 0;
    void Upload(const void* data, std::size_t bytes) {
        if (!id) glCreateBuffers(1, &id);
        glNamedBufferData(id, static_cast<GLsizeiptr>(bytes), data, GL_DYNAMIC_DRAW);
    }
    void Release() { if (id) glDeleteBuffers(1, &id); id = 0; }
};
struct VertexArray {
    GLuint id = 0;
    void Create() { if (!id) glCreateVertexArrays(1, &id); }
    void Release() { if (id) glDeleteVertexArrays(1, &id); id = 0; }
};
struct Texture2D {
    GLuint id = 0;
    void Release() { if (id) glDeleteTextures(1, &id); id = 0; }
};
}
