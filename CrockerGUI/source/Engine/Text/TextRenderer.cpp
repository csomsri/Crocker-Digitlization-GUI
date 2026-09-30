#include "Engine/Text/TextRenderer.hpp"
#include "Internal/GlyphAtlas.hpp"
#include "../Graphics/OpenGL/ShaderProgram.hpp"
#include "../Graphics/OpenGL/StateGuard.hpp"
#include <algorithm>
#include <cmath>
namespace crocker::engine {
struct TextRenderer::Impl {
    gl::Buffer buffer;
    gl::VertexArray vao;
    gl::ShaderProgram shader;
    GlyphAtlas atlas;
};
TextRenderer::TextRenderer() : impl_(std::make_unique<Impl>()) {}
TextRenderer::~TextRenderer() = default;
void TextRenderer::Release() {
    impl_->atlas.Release(); impl_->buffer.Release(); impl_->vao.Release(); impl_->shader.Release();
}
void TextRenderer::Draw(const DrawList& list, FontManager& fonts, const Viewport& viewport) {
    if (list.text.empty()) return;
    viewport.Validate();
    gl::StateGuard guard;
    auto& gpu = *impl_;
    gpu.shader.Load("text.vert", "text.frag");
    if (!gpu.vao.id) {
        gpu.vao.Create(); gpu.buffer.Upload(nullptr, 0);
        glVertexArrayVertexBuffer(gpu.vao.id, 0, gpu.buffer.id, 0, 8 * sizeof(float));
        for (GLuint i = 0; i < 3; ++i) {
            glEnableVertexArrayAttrib(gpu.vao.id, i);
            glVertexArrayAttribFormat(gpu.vao.id, i, i == 2 ? 4 : 2, GL_FLOAT, GL_FALSE, i * 2 * sizeof(float));
            glVertexArrayAttribBinding(gpu.vao.id, i, 0);
        }
    }
    struct Batch { GLuint texture; std::size_t first, count; };
    std::vector<float> vertices;
    std::vector<Batch> batches;
    for (const auto& command : list.text) {
        const auto& style = command.run.style;
        const float angle = style.rotationDegrees * 0.017453292519943295f;
        const float cosine = std::cos(angle), sine = std::sin(angle);
        // Keep each label's shadow/foreground order, and merge only adjacent
        // compatible atlas batches. No sorting across labels or primitives.
        for (int pass = style.shadow ? 0 : 1; pass < 2; ++pass) {
            for (const auto& glyph : command.run.glyphs) {
                if (glyph.bounds.width == 0 || glyph.bounds.height == 0) continue;
                const auto texture = gpu.atlas.Texture(glyph.font, fonts);
                const auto first = vertices.size() / 8;
                if (batches.empty() || batches.back().texture != texture) batches.push_back({texture, first, 0});
                auto add = [&](float x, float y, float u, float v) {
                    const float px = command.position.x + x * cosine - y * sine + (pass ? 0 : 1.35f);
                    const float py = command.position.y + x * sine + y * cosine - (pass ? 0 : 1.35f);
                    vertices.insert(vertices.end(), {2 * px / viewport.LogicalWidth() - 1,
                        2 * py / viewport.LogicalHeight() - 1, u, v,
                        pass ? style.color.r : 2.0f/255, pass ? style.color.g : 6.0f/255,
                        pass ? style.color.b : 23.0f/255, std::clamp(style.alpha, 0.0f, 1.0f) * (pass ? 1 : 0.72f)});
                };
                const auto& b = glyph.bounds; const auto& uv = glyph.uv;
                add(b.x, b.y, uv.x, uv.y + uv.height);
                add(b.x + b.width, b.y, uv.x + uv.width, uv.y + uv.height);
                add(b.x + b.width, b.y + b.height, uv.x + uv.width, uv.y);
                add(b.x, b.y, uv.x, uv.y + uv.height);
                add(b.x + b.width, b.y + b.height, uv.x + uv.width, uv.y);
                add(b.x, b.y + b.height, uv.x, uv.y);
                batches.back().count += 6;
            }
        }
    }
    gpu.buffer.Upload(vertices.data(), vertices.size() * sizeof(float));
    glDisable(GL_DEPTH_TEST); glDisable(GL_CULL_FACE); glEnable(GL_BLEND);
    glBlendEquation(GL_FUNC_ADD); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glBindSampler(0, 0); glUseProgram(gpu.shader.id); glBindVertexArray(gpu.vao.id);
    for (const auto& batch : batches) {
        glBindTextureUnit(0, batch.texture);
        glDrawArrays(GL_TRIANGLES, static_cast<GLint>(batch.first), static_cast<GLsizei>(batch.count));
    }
}
}
