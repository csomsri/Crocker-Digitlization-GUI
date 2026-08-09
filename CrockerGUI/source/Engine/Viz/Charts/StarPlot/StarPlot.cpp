#include "Engine/Viz/Charts/ChartTypes/StarPlot.hpp"

#include "../ChartOpenGL.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>

StarPlot::~StarPlot() { chart_gl::DestroyResources(vertexArray, vertexBuffer, shaderProgram); }

void StarPlot::SetData(const DataTable& data) {
    chart_gl::Validate(data);
    table = data;
}

void StarPlot::EnsureOpenGLResources() {
    if (shaderProgram == 0) chart_gl::CreateResources(vertexArray, vertexBuffer, shaderProgram);
}

void StarPlot::Render(const ChartRect& area) {
    const std::size_t axes = table.ColumnCount();
    if (table.rows.empty() || axes < 3 || area.width <= 0.0f || area.height <= 0.0f) return;
    EnsureOpenGLResources();

    GLint viewport[4];
    glGetIntegerv(GL_VIEWPORT, viewport);
    const auto plot = chart_gl::InnerArea(area, style, !title.empty());
    const float centerX = (plot.left + plot.right) * 0.5f;
    const float centerY = (plot.bottom + plot.top) * 0.5f;
    const float radius = std::min(plot.right - plot.left, plot.top - plot.bottom) * 0.38f;
    const float angleStep = 2.0f * std::numbers::pi_v<float> / static_cast<float>(axes);

    std::vector<float> spokes;
    spokes.reserve(axes * 4);
    for (std::size_t axis = 0; axis < axes; ++axis) {
        const float angle = std::numbers::pi_v<float> * 0.5f - static_cast<float>(axis) * angleStep;
        const float x = centerX + std::cos(angle) * radius;
        const float y = centerY + std::sin(angle) * radius;
        spokes.insert(spokes.end(), { chart_gl::ToNdcX(centerX, viewport), chart_gl::ToNdcY(centerY, viewport),
                                      chart_gl::ToNdcX(x, viewport), chart_gl::ToNdcY(y, viewport) });
        if (axis < table.columnNames.size()) {
            font_renderer::DrawText(
                table.columnNames[axis], centerX + std::cos(angle) * radius * 1.16f,
                centerY + std::sin(angle) * radius * 1.16f, style.axisTitleSize,
                false, style.textColor, 1.0f, style.fontPath);
        }
    }
    chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, spokes, GL_LINES,
                   style.gridColor.r, style.gridColor.g, style.gridColor.b, style.gridWidth);

    for (std::size_t series = 0; series < table.rows.size(); ++series) {
        std::vector<float> polygon;
        polygon.reserve(axes * 2);
        for (std::size_t axis = 0; axis < axes; ++axis) {
            const float amount = std::clamp(table.rows[series][axis], 0.0f, 1.0f);
            const float angle = std::numbers::pi_v<float> * 0.5f - static_cast<float>(axis) * angleStep;
            polygon.push_back(chart_gl::ToNdcX(centerX + std::cos(angle) * radius * amount, viewport));
            polygon.push_back(chart_gl::ToNdcY(centerY + std::sin(angle) * radius * amount, viewport));
        }
        const ChartColor color = table.rows.size() == 1 || style.lineColors.empty()
            ? style.lineColor : style.lineColors[series % style.lineColors.size()];
        if (style.showLineShadow) {
            std::vector<float> fan { chart_gl::ToNdcX(centerX, viewport), chart_gl::ToNdcY(centerY, viewport) };
            fan.insert(fan.end(), polygon.begin(), polygon.end());
            fan.push_back(polygon[0]); fan.push_back(polygon[1]);
            chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, fan, GL_TRIANGLE_FAN,
                           color.r, color.g, color.b, 1.0f, style.shadowOpacity);
        }
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, polygon, GL_LINE_LOOP,
                       color.r, color.g, color.b, style.lineWidth);
    }
    chart_gl::DrawLabels(vertexArray, vertexBuffer, shaderProgram, area, plot, viewport,
                         style, title, {}, {});
}
