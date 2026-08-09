#include "Engine/Viz/Charts/ChartTypes/LineChart.hpp"

#include "../ChartOpenGL.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <sstream>

namespace {
std::string FormatTick(float value, float span) {
    if (std::abs(value) < std::max(std::abs(span), 1.0f) * 0.0001f) value = 0.0f;
    const float absoluteSpan = std::abs(span);
    const int precision = absoluteSpan >= 20.0f ? 0 : (absoluteSpan >= 2.0f ? 1 : 2);
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(precision) << value;
    std::string label = stream.str();
    if (precision > 0) {
        while (!label.empty() && label.back() == '0') label.pop_back();
        if (!label.empty() && label.back() == '.') label.pop_back();
    }
    return label;
}
} // namespace

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
    const bool legendInHeader = style.showLegend && seriesCount > 0 && title.empty();
    const auto plot = chart_gl::InnerArea(area, style, !title.empty() || legendInHeader);
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

    if (style.showTickLabels) {
        const int divisions = std::max(style.gridDivisions, 1);
        for (int tick = 0; tick <= divisions; ++tick) {
            const float amount = static_cast<float>(tick) / static_cast<float>(divisions);
            const float x = plot.left + amount * (plot.right - plot.left);
            const float y = plot.bottom + amount * (plot.top - plot.bottom);
            font_renderer::DrawText(
                FormatTick(minX + amount * (maxX - minX), maxX - minX),
                x, plot.bottom - style.tickLabelSize * 0.72f,
                style.tickLabelSize, false, style.textColor, 0.9f, style.fontPath);
            font_renderer::DrawText(
                FormatTick(minY + amount * (maxY - minY), maxY - minY),
                plot.left - style.leftMargin * 0.43f, y,
                style.tickLabelSize, false, style.textColor, 0.9f, style.fontPath);
        }
    }

    if (style.showLegend && seriesCount > 0) {
        constexpr float slotWidth = 94.0f;
        const float totalWidth = slotWidth * static_cast<float>(seriesCount);
        const float startX = std::max(plot.left, plot.right - totalWidth);
        const float legendY = legendInHeader
            ? area.y + area.height - style.titleMargin * 0.5f
            : plot.top - style.legendSize * 0.8f;
        for (std::size_t series = 0; series < seriesCount; ++series) {
            const ChartColor color = seriesCount == 1 || style.lineColors.empty()
                ? style.lineColor : style.lineColors[series % style.lineColors.size()];
            const float slotLeft = startX + static_cast<float>(series) * slotWidth;
            const float swatchLeft = slotLeft + 4.0f;
            const float swatchRight = swatchLeft + 18.0f;
            const std::vector<float> swatch {
                chart_gl::ToNdcX(swatchLeft, viewport), chart_gl::ToNdcY(legendY, viewport),
                chart_gl::ToNdcX(swatchRight, viewport), chart_gl::ToNdcY(legendY, viewport),
            };
            chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, swatch, GL_LINES,
                           color.r, color.g, color.b, style.lineWidth);
            const std::size_t column = firstYColumn + series;
            const std::string label = column < table.columnNames.size()
                ? table.columnNames[column]
                : "Series " + std::to_string(series + 1);
            font_renderer::DrawText(label, slotLeft + 57.0f, legendY,
                                    style.legendSize, false, style.textColor,
                                    0.95f, style.fontPath);
        }
    }

    chart_gl::DrawLabels(vertexArray, vertexBuffer, shaderProgram, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
}
