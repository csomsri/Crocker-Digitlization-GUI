#include "Engine/Visualization/Charts/TickFormatter.hpp"
#include "Engine/Visualization/Charts/BarChart.hpp"

#include "ChartGeometry.hpp"
using crocker::engine::Primitive;

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <sstream>


void BarChart::SetData(const DataTable& data) {
    chart_geometry::Validate(data);
    table = data;
}

void BarChart::SetValueRange(float minimum, float maximum) {
    if (!std::isfinite(minimum) || !std::isfinite(maximum)) return;
    if (minimum == maximum) maximum = minimum + 1.0f;
    rangeMinimum = std::min(minimum, maximum);
    rangeMaximum = std::max(minimum, maximum);
    hasValueRange = true;
}

void BarChart::ClearValueRange() {
    hasValueRange = false;
}

void BarChart::Update(float dt) { (void)dt; }

void BarChart::Render(const ChartRect& area) {
    if (table.rows.empty() || table.ColumnCount() == 0 || area.width <= 0.0f || area.height <= 0.0f) return;
    canvas.BeginFrame();

    const std::size_t valueColumn = table.ColumnCount() >= 2 ? 1 : 0;
    float minimum = hasValueRange ? rangeMinimum : 0.0f;
    float maximum = hasValueRange ? rangeMaximum : 0.0f;
    if (!hasValueRange) {
        for (const auto& row : table.rows) {
            minimum = std::min(minimum, row[valueColumn]);
            maximum = std::max(maximum, row[valueColumn]);
        }
    }
    if (minimum == maximum) maximum = minimum + 1.0f;

    int viewport[4];
    canvas.ViewportArray(viewport);
    const auto plot = chart_geometry::InnerArea(area, style, !title.empty());
    const float zeroY = plot.bottom + chart_geometry::Normalize(0.0f, minimum, maximum) * (plot.top - plot.bottom);
    const float slotWidth = (plot.right - plot.left) / static_cast<float>(table.rows.size());
    const float gap = std::min(slotWidth * 0.16f, 6.0f);
    std::vector<std::vector<float>> bars(table.rows.size());

    for (std::size_t i = 0; i < table.rows.size(); ++i) {
        const float x0 = plot.left + static_cast<float>(i) * slotWidth + gap;
        const float x1 = plot.left + static_cast<float>(i + 1) * slotWidth - gap;
        const float valueY = plot.bottom + chart_geometry::Normalize(table.rows[i][valueColumn], minimum, maximum) * (plot.top - plot.bottom);
        const float y0 = std::min(zeroY, valueY);
        const float y1 = std::max(zeroY, valueY);
        const float nx0 = chart_geometry::ToNdcX(x0, viewport);
        const float nx1 = chart_geometry::ToNdcX(x1, viewport);
        const float ny0 = chart_geometry::ToNdcY(y0, viewport);
        const float ny1 = chart_geometry::ToNdcY(y1, viewport);
        auto& triangles = bars[i];
        triangles.insert(triangles.end(), {
            nx0, ny0, nx1, ny0, nx1, ny1,
            nx0, ny0, nx1, ny1, nx0, ny1
        });
    }

    if (style.showGrid) {
        const auto grid = chart_geometry::Grid(plot, viewport, style.gridDivisions);
        canvas.Draw( grid, Primitive::Lines,
                       style.gridColor.r, style.gridColor.g, style.gridColor.b, style.gridWidth);
    }
    if (style.showAxes) {
        const auto axes = chart_geometry::Axes(plot, viewport, zeroY);
        canvas.Draw( axes, Primitive::Lines,
                       style.axisColor.r, style.axisColor.g, style.axisColor.b, style.axisWidth);
    }
    for (std::size_t i = 0; i < bars.size(); ++i) {
        const ChartColor color = style.lineColors.empty()
            ? style.barColor
            : style.lineColors[i % style.lineColors.size()];
        canvas.Draw( bars[i], Primitive::Triangles,
                       color.r, color.g, color.b);
    }
    if (style.showTickLabels) {
        const int divisions = std::max(style.gridDivisions, 1);
        for (int tick = 0; tick <= divisions; ++tick) {
            const float amount = static_cast<float>(tick) / static_cast<float>(divisions);
            const float y = plot.bottom + amount * (plot.top - plot.bottom);
            canvas.DrawText(
                crocker::engine::TickFormatter::Format(minimum + amount * (maximum - minimum), maximum - minimum),
                plot.left - style.leftMargin * 0.43f, y,
                style.tickLabelSize, false, style.textColor, 0.9f, style.fontPath);
        }
    }
    chart_geometry::DrawLabels(canvas, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
    canvas.Flush();
}
