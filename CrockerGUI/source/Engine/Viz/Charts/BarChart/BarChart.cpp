#include "Engine/Viz/Charts/ChartTypes/BarChart.hpp"

#include "../ChartOpenGL.hpp"

#include <algorithm>
#include <limits>

BarChart::~BarChart() {
    chart_gl::DestroyResources(vertexArray, vertexBuffer, shaderProgram);
}

void BarChart::SetData(const DataTable& data) {
    chart_gl::Validate(data);
    table = data;
}

void BarChart::Update(float dt) { (void)dt; }

void BarChart::EnsureOpenGLResources() {
    if (shaderProgram == 0) {
        chart_gl::CreateResources(vertexArray, vertexBuffer, shaderProgram);
    }
}

void BarChart::Render(const ChartRect& area) {
    if (table.rows.empty() || table.ColumnCount() == 0 || area.width <= 0.0f || area.height <= 0.0f) return;
    EnsureOpenGLResources();

    const std::size_t valueColumn = table.ColumnCount() >= 2 ? 1 : 0;
    float minimum = 0.0f;
    float maximum = 0.0f;
    for (const auto& row : table.rows) {
        minimum = std::min(minimum, row[valueColumn]);
        maximum = std::max(maximum, row[valueColumn]);
    }
    if (minimum == maximum) maximum = minimum + 1.0f;

    GLint viewport[4];
    glGetIntegerv(GL_VIEWPORT, viewport);
    const auto plot = chart_gl::InnerArea(area);
    const float zeroY = plot.bottom + chart_gl::Normalize(0.0f, minimum, maximum) * (plot.top - plot.bottom);
    const float slotWidth = (plot.right - plot.left) / static_cast<float>(table.rows.size());
    const float gap = std::min(slotWidth * 0.16f, 6.0f);
    std::vector<float> triangles;
    triangles.reserve(table.rows.size() * 12);

    for (std::size_t i = 0; i < table.rows.size(); ++i) {
        const float x0 = plot.left + static_cast<float>(i) * slotWidth + gap;
        const float x1 = plot.left + static_cast<float>(i + 1) * slotWidth - gap;
        const float valueY = plot.bottom + chart_gl::Normalize(table.rows[i][valueColumn], minimum, maximum) * (plot.top - plot.bottom);
        const float y0 = std::min(zeroY, valueY);
        const float y1 = std::max(zeroY, valueY);
        const float nx0 = chart_gl::ToNdcX(x0, viewport);
        const float nx1 = chart_gl::ToNdcX(x1, viewport);
        const float ny0 = chart_gl::ToNdcY(y0, viewport);
        const float ny1 = chart_gl::ToNdcY(y1, viewport);
        triangles.insert(triangles.end(), {
            nx0, ny0, nx1, ny0, nx1, ny1,
            nx0, ny0, nx1, ny1, nx0, ny1
        });
    }

    if (style.showGrid) {
        const auto grid = chart_gl::Grid(plot, viewport);
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, grid, GL_LINES, 0.22f, 0.24f, 0.28f);
    }
    if (style.showAxes) {
        const auto axes = chart_gl::Axes(plot, viewport, zeroY);
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, axes, GL_LINES, 0.55f, 0.58f, 0.64f);
    }
    chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, triangles, GL_TRIANGLES,
                   0.24f, 0.68f, 0.42f);
}
