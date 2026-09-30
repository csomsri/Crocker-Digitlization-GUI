#include "Engine/Visualization/Charts/LegendLayout.hpp"
#include "Engine/Visualization/Charts/TickFormatter.hpp"
#include "Engine/Visualization/Charts/LineChart.hpp"

#include "ChartGeometry.hpp"
using crocker::engine::Primitive;

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <sstream>
#include <utility>

namespace {

std::vector<float> StrokeStrip(const std::vector<float>& pixelPoints,
                               const int viewport[4],
                               float widthPixels) {
    const std::size_t pointCount = pixelPoints.size() / 2;
    if (pointCount < 2) return {};

    const float halfWidth = std::max(widthPixels * 0.5f, 0.5f);
    std::vector<float> vertices;
    vertices.reserve(pointCount * 4);
    const auto xAt = [&](std::size_t index) { return pixelPoints[index * 2]; };
    const auto yAt = [&](std::size_t index) { return pixelPoints[index * 2 + 1]; };

    for (std::size_t index = 0; index < pointCount; ++index) {
        const std::size_t previous = index == 0 ? 0 : index - 1;
        const std::size_t next = index + 1 >= pointCount ? pointCount - 1 : index + 1;
        float dx = xAt(next) - xAt(previous);
        float dy = yAt(next) - yAt(previous);
        float length = std::sqrt(dx * dx + dy * dy);
        if (length <= 0.001f && index > 0) {
            dx = xAt(index) - xAt(index - 1);
            dy = yAt(index) - yAt(index - 1);
            length = std::sqrt(dx * dx + dy * dy);
        }
        if (length <= 0.001f) {
            dx = 1.0f;
            dy = 0.0f;
            length = 1.0f;
        }

        const float normalX = -dy / length * halfWidth;
        const float normalY = dx / length * halfWidth;
        const float x = xAt(index);
        const float y = yAt(index);
        vertices.insert(vertices.end(), {
            chart_geometry::ToNdcX(x + normalX, viewport), chart_geometry::ToNdcY(y + normalY, viewport),
            chart_geometry::ToNdcX(x - normalX, viewport), chart_geometry::ToNdcY(y - normalY, viewport),
        });
    }
    return vertices;
}

std::vector<float> SmoothForDisplay(const std::vector<float>& pixelPoints) {
    const std::size_t pointCount = pixelPoints.size() / 2;
    if (pointCount < 5) return pixelPoints;

    std::vector<float> current = pixelPoints;
    std::vector<float> next = pixelPoints;
    constexpr int passes = 2;
    for (int pass = 0; pass < passes; ++pass) {
        next = current;
        for (std::size_t index = 2; index + 2 < pointCount; ++index) {
            const std::size_t y = index * 2 + 1;
            next[y] = (
                current[y - 4]
                + 4.0f * current[y - 2]
                + 6.0f * current[y]
                + 4.0f * current[y + 2]
                + current[y + 4]) / 16.0f;
        }
        current.swap(next);
    }
    return current;
}

std::vector<float> BucketTrend(const std::vector<float>& pixelPoints, float plotWidth) {
    const std::size_t pointCount = pixelPoints.size() / 2;
    if (pointCount < 4) return pixelPoints;

    const std::size_t targetCount = std::clamp(
        static_cast<std::size_t>(plotWidth / 6.0f),
        std::size_t { 90 },
        std::size_t { 320 });
    if (pointCount <= targetCount) return pixelPoints;

    std::vector<float> bucketed;
    bucketed.reserve(targetCount * 2);
    for (std::size_t bucket = 0; bucket < targetCount; ++bucket) {
        const std::size_t begin = bucket * pointCount / targetCount;
        const std::size_t end = std::max(begin + 1, (bucket + 1) * pointCount / targetCount);
        float sumX = 0.0f;
        float sumY = 0.0f;
        float weightSum = 0.0f;
        const float center = (static_cast<float>(begin) + static_cast<float>(end - 1)) * 0.5f;
        const float radius = std::max(1.0f, static_cast<float>(end - begin) * 0.5f);
        for (std::size_t index = begin; index < end; ++index) {
            const float distance = std::abs(static_cast<float>(index) - center) / radius;
            const float weight = 1.0f - 0.45f * distance;
            sumX += pixelPoints[index * 2] * weight;
            sumY += pixelPoints[index * 2 + 1] * weight;
            weightSum += weight;
        }
        bucketed.push_back(sumX / std::max(weightSum, 0.001f));
        bucketed.push_back(sumY / std::max(weightSum, 0.001f));
    }
    return bucketed;
}

std::vector<float> SmoothPolyline(const std::vector<float>& pixelPoints) {
    const std::size_t pointCount = pixelPoints.size() / 2;
    if (pointCount < 3) return pixelPoints;

    std::vector<float> smoothed;
    smoothed.reserve(pointCount * 10);
    const auto xAt = [&](std::size_t index) { return pixelPoints[index * 2]; };
    const auto yAt = [&](std::size_t index) { return pixelPoints[index * 2 + 1]; };

    smoothed.push_back(xAt(0));
    smoothed.push_back(yAt(0));
    for (std::size_t index = 0; index + 1 < pointCount; ++index) {
        const std::size_t i0 = index == 0 ? 0 : index - 1;
        const std::size_t i1 = index;
        const std::size_t i2 = index + 1;
        const std::size_t i3 = std::min(index + 2, pointCount - 1);

        const float p0x = xAt(i0), p0y = yAt(i0);
        const float p1x = xAt(i1), p1y = yAt(i1);
        const float p2x = xAt(i2), p2y = yAt(i2);
        const float p3x = xAt(i3), p3y = yAt(i3);
        const float distance = std::hypot(p2x - p1x, p2y - p1y);
        const int subdivisions = std::clamp(static_cast<int>(distance / 14.0f), 5, 14);

        for (int step = 1; step <= subdivisions; ++step) {
            const float t = static_cast<float>(step) / static_cast<float>(subdivisions);
            const float t2 = t * t;
            const float t3 = t2 * t;
            const float x = 0.5f * (
                2.0f * p1x + (-p0x + p2x) * t
                + (2.0f * p0x - 5.0f * p1x + 4.0f * p2x - p3x) * t2
                + (-p0x + 3.0f * p1x - 3.0f * p2x + p3x) * t3);
            const float y = 0.5f * (
                2.0f * p1y + (-p0y + p2y) * t
                + (2.0f * p0y - 5.0f * p1y + 4.0f * p2y - p3y) * t2
                + (-p0y + 3.0f * p1y - 3.0f * p2y + p3y) * t3);
            smoothed.push_back(x);
            smoothed.push_back(y);
        }
    }
    return smoothed;
}
} // namespace

void LineChart::SetData(const DataTable& data) {
    chart_geometry::Validate(data);
    table = data;
}

void LineChart::Update(float dt) { (void)dt; }

void LineChart::Render(const ChartRect& area) {
    if (table.rows.empty() || table.ColumnCount() == 0 || area.width <= 0.0f || area.height <= 0.0f) return;
    canvas.BeginFrame();

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

    int viewport[4];
    canvas.ViewportArray(viewport);
    const bool legendInHeader = style.showLegend && seriesCount > 0 && title.empty();
    const auto plot = chart_geometry::InnerArea(area, style, !title.empty() || legendInHeader);
    std::vector<std::vector<float>> seriesPixels(seriesCount);
    std::vector<std::vector<float>> seriesPoints(seriesCount);

    for (std::size_t series = 0; series < seriesCount; ++series) {
        auto& pixels = seriesPixels[series];
        auto& points = seriesPoints[series];
        pixels.reserve(table.rows.size() * 2);
        points.reserve(table.rows.size() * 2);
        for (std::size_t i = 0; i < table.rows.size(); ++i) {
            const float x = explicitX ? table.rows[i][0] : static_cast<float>(i);
            const float y = table.rows[i][firstYColumn + series];
            const float px = plot.left + chart_geometry::Normalize(x, minX, maxX) * (plot.right - plot.left);
            const float py = plot.bottom + chart_geometry::Normalize(y, minY, maxY) * (plot.top - plot.bottom);
            pixels.push_back(px);
            pixels.push_back(py);
            points.push_back(chart_geometry::ToNdcX(px, viewport));
            points.push_back(chart_geometry::ToNdcY(py, viewport));
        }
    }

    if (style.showLineShadow && style.shadowOpacity > 0.0f) {
        const float baseline = chart_geometry::ToNdcY(plot.bottom, viewport);
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
            canvas.Draw( shadow, Primitive::TriangleStrip,
                           color.r, color.g, color.b, 1.0f, std::clamp(style.shadowOpacity, 0.0f, 1.0f));
        }
    }

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
        const ChartColor color = seriesCount == 1 || style.lineColors.empty()
            ? style.lineColor
            : style.lineColors[series % style.lineColors.size()];
        const auto bucketedPixels = BucketTrend(seriesPixels[series], plot.right - plot.left);
        const auto filteredPixels = style.smoothLines ? SmoothForDisplay(bucketedPixels) : seriesPixels[series];
        const auto smoothPixels = style.smoothLines ? SmoothPolyline(filteredPixels) : filteredPixels;
        const auto softStroke = StrokeStrip(smoothPixels, viewport, style.lineWidth + 4.4f);
        canvas.Draw( softStroke, Primitive::TriangleStrip,
                       color.r, color.g, color.b, 1.0f, 0.20f);
        const auto coreStroke = StrokeStrip(smoothPixels, viewport, style.lineWidth);
        canvas.Draw( coreStroke, Primitive::TriangleStrip,
                       color.r, color.g, color.b, 1.0f, 0.88f);
        if (!style.showPoints) continue;
        const auto& points = seriesPoints[series];
        canvas.Draw( points, Primitive::Points,
                       color.r, color.g, color.b, style.pointRadius * 2.0f);
    }

    if (style.showTickLabels) {
        const int divisions = std::max(style.gridDivisions, 1);
        for (int tick = 0; tick <= divisions; ++tick) {
            const float amount = static_cast<float>(tick) / static_cast<float>(divisions);
            const float x = plot.left + amount * (plot.right - plot.left);
            const float y = plot.bottom + amount * (plot.top - plot.bottom);
            canvas.DrawText(
                crocker::engine::TickFormatter::Format(minX + amount * (maxX - minX), maxX - minX),
                x, plot.bottom - style.tickLabelSize * 0.72f,
                style.tickLabelSize, false, style.textColor, 0.9f, style.fontPath);
            canvas.DrawText(
                crocker::engine::TickFormatter::Format(minY + amount * (maxY - minY), maxY - minY),
                plot.left - style.leftMargin * 0.43f, y,
                style.tickLabelSize, false, style.textColor, 0.9f, style.fontPath);
        }
    }

    if (style.showLegend && seriesCount > 0) {
        const float swatchWidth = std::max(22.0f, style.legendSize * 1.45f);
        constexpr float swatchGap = 12.0f;
        constexpr float slotGap = 24.0f;
        std::vector<std::string> legendLabels;
        std::vector<float> slotWidths;
        legendLabels.reserve(seriesCount);
        slotWidths.reserve(seriesCount);
        for (std::size_t series = 0; series < seriesCount; ++series) {
            const std::size_t column = firstYColumn + series;
            std::string label = column < table.columnNames.size()
                ? table.columnNames[column]
                : "Series " + std::to_string(series + 1);
            const float slotWidth = swatchWidth + swatchGap + canvas.MeasureText(label, style.legendSize, style.fontPath)
                + (series + 1 < seriesCount ? slotGap : 0.0f);
            legendLabels.push_back(std::move(label));
            slotWidths.push_back(slotWidth);
        }
        const crocker::engine::LegendLayout legend(slotWidths);
        const float totalWidth = legend.totalWidth;
        const float startX = std::max(
            plot.left,
            std::min(plot.right - totalWidth, area.x + area.width - style.plotPadding - totalWidth));
        const float legendY = legendInHeader
            ? area.y + area.height - style.titleMargin * 0.5f
            : std::min(area.y + area.height - style.plotPadding, plot.top + style.legendSize * 1.4f);
        for (std::size_t series = 0; series < seriesCount; ++series) {
            const ChartColor color = seriesCount == 1 || style.lineColors.empty()
                ? style.lineColor : style.lineColors[series % style.lineColors.size()];
            const float slotLeft = startX + legend.offsets[series];
            const float swatchLeft = slotLeft;
            const float swatchRight = swatchLeft + swatchWidth;
            const std::vector<float> swatch {
                chart_geometry::ToNdcX(swatchLeft, viewport), chart_geometry::ToNdcY(legendY, viewport),
                chart_geometry::ToNdcX(swatchRight, viewport), chart_geometry::ToNdcY(legendY, viewport),
            };
            canvas.Draw( swatch, Primitive::Lines,
                           color.r, color.g, color.b, style.lineWidth);
            const float labelLeft = swatchRight + 12.0f;
            const std::string& label = legendLabels[series];

            canvas.DrawText(label, labelLeft + canvas.MeasureText(label, style.legendSize, style.fontPath) * 0.5f, legendY,
                                    style.legendSize, false, style.textColor,
                                    0.95f, style.fontPath);
        }
    }

    chart_geometry::DrawLabels(canvas, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
    canvas.Flush();
}
