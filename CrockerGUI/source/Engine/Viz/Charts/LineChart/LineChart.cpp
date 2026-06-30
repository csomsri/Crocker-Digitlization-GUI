#include "Engine/Viz/Charts/ChartTypes/LineChart.hpp"

#include "../ChartOpenGL.hpp"

#include <algorithm>
#include <limits>

LineChart::~LineChart() {
    chart_gl::DestroyResources(vertexArray, vertexBuffer, shaderProgram);
}

void LineChart::SetData(const DataTable& data) {
    chart_gl::Validate(data);
    table = data;
}

void LineChart::Update(float dt) { (void)dt; }

void LineChart::EnsureOpenGLResources() {
    if (shaderProgram == 0) {
        chart_gl::CreateResources(vertexArray, vertexBuffer, shaderProgram);
    }
}

void LineChart::Render(const ChartRect& area) {
    if (table.rows.empty() || table.ColumnCount() == 0 || area.width <= 0.0f || area.height <= 0.0f) return;
    EnsureOpenGLResources();

    float minX = std::numeric_limits<float>::max();
    float maxX = std::numeric_limits<float>::lowest();
    float minY = std::numeric_limits<float>::max();
    float maxY = std::numeric_limits<float>::lowest();
    const bool explicitX = table.ColumnCount() >= 2;
    for (std::size_t i = 0; i < table.rows.size(); ++i) {
        const float x = explicitX ? table.rows[i][0] : static_cast<float>(i);
        const float y = explicitX ? table.rows[i][1] : table.rows[i][0];
        minX = std::min(minX, x); maxX = std::max(maxX, x);
        minY = std::min(minY, y); maxY = std::max(maxY, y);
    }

    GLint viewport[4];
    glGetIntegerv(GL_VIEWPORT, viewport);
    const auto plot = chart_gl::InnerArea(area);
    std::vector<float> points;
    points.reserve(table.rows.size() * 2);
    for (std::size_t i = 0; i < table.rows.size(); ++i) {
        const float x = explicitX ? table.rows[i][0] : static_cast<float>(i);
        const float y = explicitX ? table.rows[i][1] : table.rows[i][0];
        const float px = plot.left + chart_gl::Normalize(x, minX, maxX) * (plot.right - plot.left);
        const float py = plot.bottom + chart_gl::Normalize(y, minY, maxY) * (plot.top - plot.bottom);
        points.push_back(chart_gl::ToNdcX(px, viewport));
        points.push_back(chart_gl::ToNdcY(py, viewport));
    }

    if (style.showGrid) {
        const auto grid = chart_gl::Grid(plot, viewport);
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, grid, GL_LINES, 0.22f, 0.24f, 0.28f);
    }
    if (style.showAxes) {
        const auto axes = chart_gl::Axes(plot, viewport, plot.bottom);
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, axes, GL_LINES, 0.55f, 0.58f, 0.64f);
    }
    chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, points, GL_LINE_STRIP,
                   0.10f, 0.72f, 0.95f, style.lineWidth);
    chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, points, GL_POINTS,
                   0.10f, 0.72f, 0.95f, style.pointRadius * 2.0f);
}
