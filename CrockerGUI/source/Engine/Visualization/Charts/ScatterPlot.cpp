#include "Engine/Visualization/Charts/ScatterPlot.hpp"

#include "ChartGeometry.hpp"
using crocker::engine::Primitive;

#include <algorithm>
#include <limits>
#include <vector>

void ScatterPlot::SetData(const DataTable& data) {
    chart_geometry::Validate(data);
    table = data;
}

void ScatterPlot::Update(float dt) {
    (void)dt;
}

void ScatterPlot::Render(const ChartRect& area) {
    const std::size_t columnCount = table.ColumnCount();
    if (table.rows.empty() || columnCount < 2 || area.width <= 0.0f || area.height <= 0.0f) return;
    canvas.BeginFrame();

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

    int viewport[4];
    canvas.ViewportArray(viewport);
    const auto plot = chart_geometry::InnerArea(area, style, !title.empty());

    if (style.showGrid) {
        const auto grid = chart_geometry::Grid(plot, viewport, style.gridDivisions);
        canvas.Draw( grid, Primitive::Lines,
                       style.gridColor.r, style.gridColor.g, style.gridColor.b, style.gridWidth);
    }
    if (style.showAxes) {
        const auto axes = chart_geometry::Axes(plot, viewport, plot.bottom);
        canvas.Draw( axes, Primitive::Lines,
                       style.axisColor.r, style.axisColor.g, style.axisColor.b, style.axisWidth);
    }

    for (std::size_t series = 0; series < seriesCount; ++series) {
        std::vector<float> points;
        points.reserve(table.rows.size() * 2);
        for (const auto& row : table.rows) {
            const float x = plot.left + chart_geometry::Normalize(row[0], minimumX, maximumX) * (plot.right - plot.left);
            const float y = plot.bottom + chart_geometry::Normalize(row[series + 1], minimumY, maximumY) * (plot.top - plot.bottom);
            points.push_back(chart_geometry::ToNdcX(x, viewport));
            points.push_back(chart_geometry::ToNdcY(y, viewport));
        }

        const ChartColor color = seriesCount == 1 || style.lineColors.empty()
            ? style.lineColor
            : style.lineColors[series % style.lineColors.size()];
        canvas.Draw( points, Primitive::Points,
                       color.r, color.g, color.b, style.pointRadius * 2.0f);
    }

    chart_geometry::DrawLabels(canvas, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
    canvas.Flush();
}
