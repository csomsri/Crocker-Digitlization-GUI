#pragma once
#include "Engine/Core/Viewport.hpp"
#include "Engine/Text/TextRenderer.hpp"
#include <cstdint>
#include <memory>
#include <vector>
namespace crocker::engine {
enum class Primitive { Points, Lines, LineStrip, LineLoop, Triangles, TriangleStrip, TriangleFan };
class RenderContext {
public:
    RenderContext();
    ~RenderContext();
    RenderContext(const RenderContext&) = delete;
    RenderContext& operator=(const RenderContext&) = delete;
    static void LoadOpenGL(void* (*loader)(const char*));
    // Host announces the CURRENT native context on each paint/cleanup callback.
    // This is only a thread-local identity, never a shared resource registry.
    static void SetCurrentContext(std::uintptr_t identity);
    void RequireCurrent();
    void Release();
    FontManager& Fonts();
    void SetPixelRatio(float ratio);
    Viewport CurrentViewport() const;
    void Draw(const std::vector<float>& ndcVertices, Primitive mode, Color color, float size, float alpha);
    void DrawText(const DrawList& list, const Viewport& viewport);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    std::uintptr_t owner_ = 0;
    float pixelRatio_ = 1;
};
}
