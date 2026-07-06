#include "Engine/Viz/Charts/ChartTypes/HeatmapChart.hpp"

#include "../ChartOpenGL.hpp"

#include <algorithm>
#include <limits>

HeatmapChart::~HeatmapChart() { chart_gl::DestroyResources(vertexArray, vertexBuffer, shaderProgram); }

void HeatmapChart::SetData(const DataTable& data) {
    chart_gl::Validate(data);
    table = data;
}

void HeatmapChart::EnsureOpenGLResources() {
    if (shaderProgram == 0) chart_gl::CreateResources(vertexArray, vertexBuffer, shaderProgram);
}

void HeatmapChart::Render(const ChartRect& area) {
    const std::size_t columns = table.ColumnCount();
    if (table.rows.empty() || columns == 0 || area.width <= 0.0f || area.height <= 0.0f) return;
    EnsureOpenGLResources();

    float minimum = std::numeric_limits<float>::max();
    float maximum = std::numeric_limits<float>::lowest();
    for (const auto& row : table.rows) for (float value : row) {
        minimum = std::min(minimum, value);
        maximum = std::max(maximum, value);
    }

    GLint viewport[4];
    glGetIntegerv(GL_VIEWPORT, viewport);
    const auto plot = chart_gl::InnerArea(area, style, !title.empty());
    const float cellWidth = (plot.right - plot.left) / static_cast<float>(columns);
    const float cellHeight = (plot.top - plot.bottom) / static_cast<float>(table.rows.size());

    for (std::size_t row = 0; row < table.rows.size(); ++row) {
        for (std::size_t column = 0; column < columns; ++column) {
            const float amount = chart_gl::Normalize(table.rows[row][column], minimum, maximum);
            const ChartColor color {
                style.heatLowColor.r + amount * (style.heatHighColor.r - style.heatLowColor.r),
                style.heatLowColor.g + amount * (style.heatHighColor.g - style.heatLowColor.g),
                style.heatLowColor.b + amount * (style.heatHighColor.b - style.heatLowColor.b)
            };
            const float x0 = plot.left + static_cast<float>(column) * cellWidth;
            const float x1 = x0 + cellWidth;
            const float y0 = plot.top - static_cast<float>(row + 1) * cellHeight;
            const float y1 = y0 + cellHeight;
            const float nx0 = chart_gl::ToNdcX(x0, viewport); const float nx1 = chart_gl::ToNdcX(x1, viewport);
            const float ny0 = chart_gl::ToNdcY(y0, viewport); const float ny1 = chart_gl::ToNdcY(y1, viewport);
            const std::vector<float> vertices { nx0, ny0, nx1, ny0, nx1, ny1, nx0, ny0, nx1, ny1, nx0, ny1 };
            chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, vertices, GL_TRIANGLES, color.r, color.g, color.b);
        }
    }
    chart_gl::DrawLabels(vertexArray, vertexBuffer, shaderProgram, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
}
