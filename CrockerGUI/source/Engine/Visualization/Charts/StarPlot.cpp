#include "Engine/Visualization/Charts/StarPlot.hpp"

#include "ChartGeometry.hpp"
using crocker::engine::Primitive;

#include <algorithm>
#include <cmath>
#include <numbers>

void StarPlot::SetData(const DataTable& data) {
    chart_geometry::Validate(data);
    table = data;
}

void StarPlot::Render(const ChartRect& area) {
    const std::size_t axes = table.ColumnCount();
    if (table.rows.empty() || axes < 3 || area.width <= 0.0f || area.height <= 0.0f) return;
    canvas.BeginFrame();

    int viewport[4];
    canvas.ViewportArray(viewport);
    const auto plot = chart_geometry::InnerArea(area, style, !title.empty());
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
        spokes.insert(spokes.end(), { chart_geometry::ToNdcX(centerX, viewport), chart_geometry::ToNdcY(centerY, viewport),
                                      chart_geometry::ToNdcX(x, viewport), chart_geometry::ToNdcY(y, viewport) });
        if (axis < table.columnNames.size()) {
            canvas.DrawText(
                table.columnNames[axis], centerX + std::cos(angle) * radius * 1.16f,
                centerY + std::sin(angle) * radius * 1.16f, style.axisTitleSize,
                false, style.textColor, 1.0f, style.fontPath);
        }
    }
    canvas.Draw( spokes, Primitive::Lines,
                   style.gridColor.r, style.gridColor.g, style.gridColor.b, style.gridWidth);

    for (std::size_t series = 0; series < table.rows.size(); ++series) {
        std::vector<float> polygon;
        polygon.reserve(axes * 2);
        for (std::size_t axis = 0; axis < axes; ++axis) {
            const float amount = std::clamp(table.rows[series][axis], 0.0f, 1.0f);
            const float angle = std::numbers::pi_v<float> * 0.5f - static_cast<float>(axis) * angleStep;
            polygon.push_back(chart_geometry::ToNdcX(centerX + std::cos(angle) * radius * amount, viewport));
            polygon.push_back(chart_geometry::ToNdcY(centerY + std::sin(angle) * radius * amount, viewport));
        }
        const ChartColor color = table.rows.size() == 1 || style.lineColors.empty()
            ? style.lineColor : style.lineColors[series % style.lineColors.size()];
        if (style.showLineShadow) {
            std::vector<float> fan { chart_geometry::ToNdcX(centerX, viewport), chart_geometry::ToNdcY(centerY, viewport) };
            fan.insert(fan.end(), polygon.begin(), polygon.end());
            fan.push_back(polygon[0]); fan.push_back(polygon[1]);
            canvas.Draw( fan, Primitive::TriangleFan,
                           color.r, color.g, color.b, 1.0f, style.shadowOpacity);
        }
        canvas.Draw( polygon, Primitive::LineLoop,
                       color.r, color.g, color.b, style.lineWidth);
    }
    chart_geometry::DrawLabels(canvas, area, plot, viewport,
                         style, title, {}, {});
    canvas.Flush();
}
