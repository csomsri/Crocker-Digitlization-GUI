#include "Engine/Graphics/Canvas2D.hpp"
namespace crocker::engine {
void Canvas2D::BeginFrame() {
    context_.RequireCurrent(); viewport_ = context_.CurrentViewport(); viewport_.Validate(); list_.Clear();
}
void Canvas2D::Flush() {
    if (!list_.text.empty()) { context_.DrawText(list_, viewport_); list_.Clear(); }
}
void Canvas2D::ViewportArray(int result[4]) const {
    result[0] = result[1] = 0;
    result[2] = std::max(1, static_cast<int>(std::round(viewport_.LogicalWidth())));
    result[3] = std::max(1, static_cast<int>(std::round(viewport_.LogicalHeight())));
}
void Canvas2D::Draw(const std::vector<float>& vertices, Primitive mode, float r, float g, float b, float size, float alpha) {
    Flush(); context_.Draw(vertices, mode, {r, g, b}, size, alpha);
}
void Canvas2D::DrawText(const TextRun& run, Point position) { list_.text.push_back({run, position}); }
void Canvas2D::DrawText(const std::string& text, float x, float y, float size, bool vertical, Color color, float alpha, const std::string& path) {
    if (text.empty() || size <= 0) return;
    TextStyle style; style.font = context_.Fonts().Load(path); style.size = size; style.color = color;
    style.alpha = alpha; style.rotationDegrees = vertical ? 90.0f : 0.0f;
    DrawText(TextLayout(context_.Fonts()).Layout(text, style), {x, y});
}
float Canvas2D::MeasureText(const std::string& text, float size, const std::string& path) {
    TextStyle style; style.font = context_.Fonts().Load(path); style.size = size;
    return TextLayout(context_.Fonts()).Layout(text, style).advance;
}
}
