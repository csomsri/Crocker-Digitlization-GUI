#include "Engine/Viz/Charts/ChartTypes/AlarmTimelineChart.hpp"

#include "../ChartOpenGL.hpp"

#include <algorithm>
#include <limits>

AlarmTimelineChart::~AlarmTimelineChart() { chart_gl::DestroyResources(vertexArray, vertexBuffer, shaderProgram); }

void AlarmTimelineChart::SetData(const DataTable& data) {
    chart_gl::Validate(data);
    if (!data.rows.empty() && data.ColumnCount() < 3) {
        throw std::invalid_argument("AlarmTimelineChart requires Start, End, and Severity columns");
    }
    table = data;
}

void AlarmTimelineChart::EnsureOpenGLResources() {
    if (shaderProgram == 0) chart_gl::CreateResources(vertexArray, vertexBuffer, shaderProgram);
}

void AlarmTimelineChart::Render(const ChartRect& area) {
    if (table.rows.empty() || area.width <= 0.0f || area.height <= 0.0f) return;
    EnsureOpenGLResources();

    float start = std::numeric_limits<float>::max();
    float end = std::numeric_limits<float>::lowest();
    for (const auto& row : table.rows) {
        start = std::min(start, row[0]);
        end = std::max(end, row[1]);
    }

    GLint viewport[4];
    glGetIntegerv(GL_VIEWPORT, viewport);
    const auto plot = chart_gl::InnerArea(area, style, !title.empty());
    const float laneHeight = (plot.top - plot.bottom) / static_cast<float>(table.rows.size());

    for (std::size_t lane = 0; lane < table.rows.size(); ++lane) {
        const auto& row = table.rows[lane];
        const float x0 = plot.left + chart_gl::Normalize(row[0], start, end) * (plot.right - plot.left);
        const float x1 = plot.left + chart_gl::Normalize(row[1], start, end) * (plot.right - plot.left);
        const float y0 = plot.top - static_cast<float>(lane + 1) * laneHeight + 1.0f;
        const float y1 = y0 + laneHeight - 2.0f;
        const ChartColor color = row[2] >= 2.0f ? style.alarmColor
            : (row[2] >= 1.0f ? style.warningColor : style.normalColor);
        const float nx0 = chart_gl::ToNdcX(x0, viewport); const float nx1 = chart_gl::ToNdcX(x1, viewport);
        const float ny0 = chart_gl::ToNdcY(y0, viewport); const float ny1 = chart_gl::ToNdcY(y1, viewport);
        const std::vector<float> vertices { nx0, ny0, nx1, ny0, nx1, ny1, nx0, ny0, nx1, ny1, nx0, ny1 };
        chart_gl::Draw(vertexArray, vertexBuffer, shaderProgram, vertices, GL_TRIANGLES, color.r, color.g, color.b);
    }
    chart_gl::DrawLabels(vertexArray, vertexBuffer, shaderProgram, area, plot, viewport,
                         style, title, xAxisTitle, yAxisTitle);
}
