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

    const std::size_t columnCount = table.ColumnCount();
    const bool explicitX = columnCount >= 2;
    const std::size_t firstYColumn = explicitX ? 1 : 0;
    const std::size_t seriesCount = explicitX ? columnCount - 1 : 1;
    float minX = std::numeric_limits<float>::max();
    float maxX = std::numeric_limits<float>::lowest();
    float minY = std::numeric_limits<float>::max();
    float maxY = std::numeric_limits<float>::lowest();

    for (std::size_t i = 0; i < table.rows.size(); ++i) {
        const float x = explicitX ? table.rows[i][0] : static_cast<float>(i);
        minX = std::min(minX, x);
        maxX = std::max(maxX, x);
        for (std::size_t series = 0; series < seriesCount; ++series) {
            const float y = table.rows[i][firstYColumn + series];
            minY = std::min(minY, y);
            maxY = std::max(maxY, y);
        }
    }

    GLint viewport[4];
    glGetIntegerv(GL_VIEWPORT, viewport);
    const auto plot = chart_gl::InnerArea(area, style, !title.empty());
    std::vector<std::vector<float>> seriesPoints(seriesCount);

    for (std::size_t series = 0; series < seriesCount; ++series) {
        auto& points = seriesPoints[series];
        points.reserve(table.rows.size() * 2);
        for (std::size_t i = 0; i < table.rows.size(); ++i) {
            const float x = explicitX ? table.rows[i][0] : static_cast<float>(i);
            const float y = table.rows[i][firstYColumn + series];
            const float px = plot.left + chart_gl::Normalize(x, minX, maxX) * (plot.right - plot.left);
            const float py = plot.bottom + chart_gl::Normalize(y, minY, maxY) * (plot.top - plot.bottom);
            points.push_back(chart_gl::ToNdcX(px, viewport));
            points.push_back(chart_gl::ToNdcY(py, viewport));
        }
    }

    if (style.showLineShadow && style.shadowOpacity > 0.0f) {
        const float baseline = chart_gl::ToNdcY(plot.bottom, viewport);
        for (std::size_t series = 0; series < seriesCount; ++series) {
            const auto& points = seriesPoints[series];
            std::vector<float> shadow;
            shadow.reserve(points.size() * 2);
            for (std::size_t point = 0; point < points.size(); point += 2) {
                shadow.insert(shadow.end(), { points[point], baseline, points[point], points[point + 1] });
            }
            const ChartColor color = seriesCount == 1 || style.lineColors.empty()
                ? style.lineColor
                : style.lineColors[series % style.lineColors.size()];
            chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, shadow, GL_TRIANGLE_STRIP,
                           color.r, color.g, color.b, 1.0f, std::clamp(style.shadowOpacity, 0.0f, 1.0f));
        }
    }

    if (style.showGrid) {
        const auto grid = chart_gl::Grid(plot, viewport, style.gridDivisions);
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, grid, GL_LINES,
                       style.gridColor.r, style.gridColor.g, style.gridColor.b, style.gridWidth);
    }
    if (style.showAxes) {
        const auto axes = chart_gl::Axes(plot, viewport, plot.bottom);
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, axes, GL_LINES,
                       style.axisColor.r, style.axisColor.g, style.axisColor.b, style.axisWidth);
    }

    for (std::size_t series = 0; series < seriesCount; ++series) {
        const ChartColor color = seriesCount == 1 || style.lineColors.empty()
            ? style.lineColor
            : style.lineColors[series % style.lineColors.size()];
        const auto& points = seriesPoints[series];
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, points, GL_LINE_STRIP,
                       color.r, color.g, color.b, style.lineWidth);
        if (!style.showPoints) continue;
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, points, GL_POINTS,
                       color.r, color.g, color.b, style.pointRadius * 2.0f);
    }

    chart_gl::DrawLabels(vertexArray, vertexBuffer, shaderProgram, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
}
