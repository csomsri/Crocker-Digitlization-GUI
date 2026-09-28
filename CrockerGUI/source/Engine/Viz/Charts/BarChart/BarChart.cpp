#include "Engine/Viz/Charts/ChartTypes/BarChart.hpp"

#include "../ChartOpenGL.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <sstream>
#include <chrono>

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

BarChart::~BarChart() {
    if (queriesInitialized) {
        glDeleteQueries(2, gpuQueries);
    }
    chart_gl::DestroyResources(vertexArray, vertexBuffer, shaderProgram);
}

void BarChart::SetData(const DataTable& data) {
    auto start = std::chrono::high_resolution_clock::now();

    chart_gl::Validate(data);
    table = data;

    auto end = std::chrono::high_resolution_clock::now();
    setDataCpuMs = std::chrono::duration<double, std::milli>(end - start).count();
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

void BarChart::EnsureOpenGLResources() {
    if (shaderProgram == 0) {
        chart_gl::CreateResources(vertexArray, vertexBuffer, shaderProgram);
    }
    if (!queriesInitialized) {
        glGenQueries(2, gpuQueries);
        queriesInitialized = true;
    }
}

void BarChart::Render(const ChartRect& area) {
    if (table.rows.empty() || table.ColumnCount() == 0 || area.width <= 0.0f || area.height <= 0.0f) return;
    EnsureOpenGLResources();

    // Calculate fps
    auto now = std::chrono::high_resolution_clock::now();
    if (lastFrameTime.time_since_epoch().count() > 0) {
        float deltaSec = std::chrono::duration<float>(now - lastFrameTime).count();
        fpsTimer += deltaSec;
        frameCount++;
        if (fpsTimer >= 0.5f) {
            fps = static_cast<float>(frameCount) / fpsTimer;
            frameCount = 0;
            fpsTimer = 0.0f;
        }
    }
    lastFrameTime = now;

    auto cpuRenderStart = std::chrono::high_resolution_clock::now();
    glBeginQuery(GL_TIME_ELAPSED, gpuQueries[currentQueryIdx]);

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

    GLint viewport[4];
    glGetIntegerv(GL_VIEWPORT, viewport);
    const auto plot = chart_gl::InnerArea(area, style, !title.empty());
    const float zeroY = plot.bottom + chart_gl::Normalize(0.0f, minimum, maximum) * (plot.top - plot.bottom);
    const float slotWidth = (plot.right - plot.left) / static_cast<float>(table.rows.size());
    const float gap = std::min(slotWidth * 0.16f, 6.0f);
    std::vector<std::vector<float>> bars(table.rows.size());

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
        auto& triangles = bars[i];
        triangles.insert(triangles.end(), {
            nx0, ny0, nx1, ny0, nx1, ny1,
            nx0, ny0, nx1, ny1, nx0, ny1
        });
    }

    if (style.showGrid) {
        const auto grid = chart_gl::Grid(plot, viewport, style.gridDivisions);
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, grid, GL_LINES,
                       style.gridColor.r, style.gridColor.g, style.gridColor.b, style.gridWidth);
    }
    if (style.showAxes) {
        const auto axes = chart_gl::Axes(plot, viewport, zeroY);
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, axes, GL_LINES,
                       style.axisColor.r, style.axisColor.g, style.axisColor.b, style.axisWidth);
    }
    for (std::size_t i = 0; i < bars.size(); ++i) {
        const ChartColor color = style.lineColors.empty()
            ? style.barColor
            : style.lineColors[i % style.lineColors.size()];
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, bars[i], GL_TRIANGLES,
                       color.r, color.g, color.b);
    }
    if (style.showTickLabels) {
        const int divisions = std::max(style.gridDivisions, 1);
        for (int tick = 0; tick <= divisions; ++tick) {
            const float amount = static_cast<float>(tick) / static_cast<float>(divisions);
            const float y = plot.bottom + amount * (plot.top - plot.bottom);
            font_renderer::DrawText(
                FormatTick(minimum + amount * (maximum - minimum), maximum - minimum),
                plot.left - style.leftMargin * 0.43f, y,
                style.tickLabelSize, false, style.textColor, 0.9f, style.fontPath);
        }
    }
    chart_gl::DrawLabels(vertexArray, vertexBuffer, shaderProgram, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
    glEndQuery(GL_TIME_ELAPSED);

    GLuint prevQuery = gpuQueries[(currentQueryIdx + 1) % 2];
    GLint available = 0;
    glGetQueryObjectiv(prevQuery, GL_QUERY_RESULT_AVAILABLE, &available);
    if (available) {
        GLuint64 timeNs = 0;
        glGetQueryObjectui64v(prevQuery, GL_QUERY_RESULT, &timeNs);
        renderGpuMs = static_cast<double>(timeNs) / 1000000.0;
    }
    currentQueryIdx = (currentQueryIdx + 1) % 2;

    auto cpuRenderEnd = std::chrono::high_resolution_clock::now();
    renderCpuMs = std::chrono::duration<double, std::milli>(cpuRenderEnd - cpuRenderStart).count();

    // Statoverlay
    std::ostringstream statsText;
    statsText << std::fixed << std::setprecision(2)
              << "FPS: " << fps 
              << " | SetData CPU: " << setDataCpuMs << "ms"
              << " | Render CPU: " << renderCpuMs << "ms"
              << " | GPU: " << renderGpuMs << "ms";

    font_renderer::DrawText(
        statsText.str(),
        plot.left + 10.0f, plot.top - 20.0f,
        12.0f, false, style.textColor, 1.0f, style.fontPath
    );
}