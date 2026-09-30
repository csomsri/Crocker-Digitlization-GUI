#include "Engine/Visualization/Charts/BulletChart.hpp"

#include "ChartGeometry.hpp"
using crocker::engine::Primitive;

#include <algorithm>

namespace {

std::vector<float> Rectangle(float x0, float y0, float x1, float y1, const int viewport[4]) {
    const float nx0 = chart_geometry::ToNdcX(x0, viewport); const float nx1 = chart_geometry::ToNdcX(x1, viewport);
    const float ny0 = chart_geometry::ToNdcY(y0, viewport); const float ny1 = chart_geometry::ToNdcY(y1, viewport);
    return { nx0, ny0, nx1, ny0, nx1, ny1, nx0, ny0, nx1, ny1, nx0, ny1 };
}

} // namespace

void BulletChart::SetData(const DataTable& data) {
    chart_geometry::Validate(data);
    if (!data.rows.empty() && data.ColumnCount() < 4) {
        throw std::invalid_argument("BulletChart requires Value, Target, Minimum, and Maximum columns");
    }
    table = data;
}

void BulletChart::Render(const ChartRect& area) {
    if (table.rows.empty() || area.width <= 0.0f || area.height <= 0.0f) return;
    canvas.BeginFrame();

    int viewport[4];
    canvas.ViewportArray(viewport);
    const auto plot = chart_geometry::InnerArea(area, style, !title.empty());
    const float laneHeight = (plot.top - plot.bottom) / static_cast<float>(table.rows.size());

    for (std::size_t lane = 0; lane < table.rows.size(); ++lane) {
        const auto& row = table.rows[lane];
        const float minimum = std::min(row[2], row[3]);
        const float maximum = std::max(row[2], row[3]);
        const float yCenter = plot.top - (static_cast<float>(lane) + 0.5f) * laneHeight;
        const float xValue = plot.left + std::clamp(chart_geometry::Normalize(row[0], minimum, maximum), 0.0f, 1.0f)
            * (plot.right - plot.left);
        const float xTarget = plot.left + std::clamp(chart_geometry::Normalize(row[1], minimum, maximum), 0.0f, 1.0f)
            * (plot.right - plot.left);

        const auto background = Rectangle(plot.left, yCenter - laneHeight * 0.30f,
                                           plot.right, yCenter + laneHeight * 0.30f, viewport);
        canvas.Draw( background, Primitive::Triangles,
                       style.gridColor.r, style.gridColor.g, style.gridColor.b);
        const auto value = Rectangle(plot.left, yCenter - laneHeight * 0.16f,
                                     xValue, yCenter + laneHeight * 0.16f, viewport);
        canvas.Draw( value, Primitive::Triangles,
                       style.lineColor.r, style.lineColor.g, style.lineColor.b);
        const std::vector<float> target {
            chart_geometry::ToNdcX(xTarget, viewport), chart_geometry::ToNdcY(yCenter - laneHeight * 0.24f, viewport),
            chart_geometry::ToNdcX(xTarget, viewport), chart_geometry::ToNdcY(yCenter + laneHeight * 0.24f, viewport)
        };
        canvas.Draw( target, Primitive::Lines,
                       style.textColor.r, style.textColor.g, style.textColor.b, style.axisWidth * 2.0f);
    }
    chart_geometry::DrawLabels(canvas, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
    canvas.Flush();
}
