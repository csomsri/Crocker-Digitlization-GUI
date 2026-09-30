#pragma once
#include "Engine/Graphics/RenderContext.hpp"
namespace crocker::engine {
class Canvas2D {
public:
    explicit Canvas2D(RenderContext& context) : context_(context) {}
    void BeginFrame();
    void Flush();
    void ViewportArray(int result[4]) const;
    void Draw(const std::vector<float>& ndcVertices, Primitive mode,
              float r, float g, float b, float size = 1, float alpha = 1);
    void DrawText(const TextRun& run, Point position);
    // Convenience bridge for existing chart/gauge call sites.
    void DrawText(const std::string& text, float x, float y, float size,
                  bool vertical, Color color, float alpha = 1, const std::string& fontPath = {});
    float MeasureText(const std::string& text, float size, const std::string& fontPath = {});
private:
    RenderContext& context_;
    Viewport viewport_;
    DrawList list_;
};
}
