#include "Engine/Viz/Charts/ChartTypes/ScatterPlot.hpp"

#include "../ChartOpenGL.hpp"

#include <algorithm>
#include <limits>
#include <vector>

ScatterPlot::~ScatterPlot() {
    chart_gl::DestroyResources(vertexArray, vertexBuffer, shaderProgram);
}

void ScatterPlot::SetData(const DataTable& data) {
    chart_gl::Validate(data);
    table = data;
}

void ScatterPlot::Update(float dt) {
    (void)dt;
}

void ScatterPlot::EnsureOpenGLResources() {
    if (shaderProgram == 0) {
        chart_gl::CreateResources(vertexArray, vertexBuffer, shaderProgram);
    }
}

void ScatterPlot::Render(const ChartRect& area) {
    const std::size_t columnCount = table.ColumnCount();
    if (table.rows.empty() || columnCount < 2 || area.width <= 0.0f || area.height <= 0.0f) return;
    EnsureOpenGLResources();

    const std::size_t seriesCount = columnCount - 1;
    float minimumX = std::numeric_limits<float>::max();
    float maximumX = std::numeric_limits<float>::lowest();
    float minimumY = std::numeric_limits<float>::max();
    float maximumY = std::numeric_limits<float>::lowest();

    for (const auto& row : table.rows) {
        minimumX = std::min(minimumX, row[0]);
        maximumX = std::max(maximumX, row[0]);
        for (std::size_t series = 0; series < seriesCount; ++series) {
            minimumY = std::min(minimumY, row[series + 1]);
            maximumY = std::max(maximumY, row[series + 1]);
        }
    }

    GLint viewport[4];
    glGetIntegerv(GL_VIEWPORT, viewport);
    const auto plot = chart_gl::InnerArea(area, style, !title.empty());

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
        std::vector<float> points;
        points.reserve(table.rows.size() * 2);
        for (const auto& row : table.rows) {
            const float x = plot.left + chart_gl::Normalize(row[0], minimumX, maximumX) * (plot.right - plot.left);
            const float y = plot.bottom + chart_gl::Normalize(row[series + 1], minimumY, maximumY) * (plot.top - plot.bottom);
            points.push_back(chart_gl::ToNdcX(x, viewport));
            points.push_back(chart_gl::ToNdcY(y, viewport));
        }

        const ChartColor color = seriesCount == 1 || style.lineColors.empty()
            ? style.lineColor
            : style.lineColors[series % style.lineColors.size()];
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, points, GL_POINTS,
                       color.r, color.g, color.b, style.pointRadius * 2.0f);
    }

    chart_gl::DrawLabels(vertexArray, vertexBuffer, shaderProgram, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
}
