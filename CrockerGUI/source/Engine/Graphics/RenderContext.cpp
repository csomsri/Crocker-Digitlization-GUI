#include "Engine/Graphics/RenderContext.hpp"
#include "OpenGL/Objects.hpp"
#include "OpenGL/ShaderProgram.hpp"
#include "OpenGL/StateGuard.hpp"
#include <stdexcept>
namespace crocker::engine {
namespace { thread_local std::uintptr_t currentContext = 0; }
struct RenderContext::Impl {
    FontManager fonts;
    TextRenderer text;
    gl::Buffer buffer;
    gl::VertexArray vao;
    gl::ShaderProgram shader;
    GLint colorLocation = -1;
};
RenderContext::RenderContext() : impl_(std::make_unique<Impl>()) {}
// Hosts call Release while current. A destructor may run after Qt has changed
// or destroyed native contexts, so it must never infer GL ownership from a
// stale thread-local identity and delete another context's resources.
RenderContext::~RenderContext() = default;
void RenderContext::SetCurrentContext(std::uintptr_t identity) { currentContext = identity; }
void RenderContext::LoadOpenGL(void* (*loader)(const char*)) {
    if (!loader || !gladLoadGLLoader(loader) || !GLAD_GL_VERSION_4_6)
        throw std::runtime_error("Crocker graphics requires an OpenGL 4.6 core context.");
}
void RenderContext::RequireCurrent() {
    if (!currentContext) throw std::runtime_error("The host must identify its current OpenGL context before rendering.");
    if (owner_ && owner_ != currentContext) throw std::runtime_error("Rendering resources belong to a different OpenGL context.");
    owner_ = currentContext;
}
void RenderContext::Release() {
    if (!owner_) return;
    RequireCurrent();
    impl_->text.Release(); impl_->buffer.Release(); impl_->vao.Release(); impl_->shader.Release();
    owner_ = 0;
}
FontManager& RenderContext::Fonts() { return impl_->fonts; }
void RenderContext::SetPixelRatio(float ratio) { Viewport{1, 1, ratio}.Validate(); pixelRatio_ = ratio; }
Viewport RenderContext::CurrentViewport() const {
    GLint viewport[4]; glGetIntegerv(GL_VIEWPORT, viewport);
    return {viewport[2], viewport[3], pixelRatio_};
}
void RenderContext::Draw(const std::vector<float>& vertices, Primitive mode, Color color, float size, float alpha) {
    if (vertices.empty()) return;
    RequireCurrent();
    gl::StateGuard guard;
    auto& gpu = *impl_;
    if (!gpu.shader.id) {
        gpu.shader.Load("primitive2d.vert", "primitive2d.frag");
        gpu.colorLocation = glGetUniformLocation(gpu.shader.id, "primitiveColor");
    }
    gpu.buffer.Upload(vertices.data(), vertices.size() * sizeof(float));
    if (!gpu.vao.id) {
        gpu.vao.Create(); glVertexArrayVertexBuffer(gpu.vao.id, 0, gpu.buffer.id, 0, 2 * sizeof(float));
        glEnableVertexArrayAttrib(gpu.vao.id, 0);
        glVertexArrayAttribFormat(gpu.vao.id, 0, 2, GL_FLOAT, GL_FALSE, 0);
        glVertexArrayAttribBinding(gpu.vao.id, 0, 0);
    }
    glDisable(GL_DEPTH_TEST); glDisable(GL_CULL_FACE); glEnable(GL_BLEND);
    glBlendEquation(GL_FUNC_ADD); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glUseProgram(gpu.shader.id); glBindVertexArray(gpu.vao.id);
    glProgramUniform4f(gpu.shader.id, gpu.colorLocation, color.r, color.g, color.b, std::clamp(alpha, 0.0f, 1.0f));
    constexpr GLenum modes[] = {GL_POINTS, GL_LINES, GL_LINE_STRIP, GL_LINE_LOOP, GL_TRIANGLES, GL_TRIANGLE_STRIP, GL_TRIANGLE_FAN};
    if (mode == Primitive::Points) glPointSize(std::max(1.0f, size * pixelRatio_));
    // Thick curves are already tessellated by chart geometry; native wide
    // lines are deliberately avoided for core-profile driver compatibility.
    glDrawArrays(modes[static_cast<int>(mode)], 0, static_cast<GLsizei>(vertices.size() / 2));
}
void RenderContext::DrawText(const DrawList& list, const Viewport& viewport) {
    RequireCurrent(); impl_->text.Draw(list, impl_->fonts, viewport);
}
}
