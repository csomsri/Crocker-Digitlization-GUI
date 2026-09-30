#pragma once
#include "Engine/Visualization/Charts/AxisLayout.hpp"

#include "Engine/Graphics/Canvas2D.hpp"
#include "Engine/Visualization/Data/DataTable.hpp"

#include "Engine/Visualization/Charts/ChartRect.hpp"
#include "Engine/Visualization/Charts/ChartStyle.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace chart_geometry {

inline void Validate(const DataTable& table) {
    const std::size_t columns = table.ColumnCount();
    for (const auto& row : table.rows) {
        if (row.size() != columns) {
            throw std::invalid_argument("Every DataTable row must have the same number of columns");
        }
    }
}

inline float ToNdcX(float pixelX, const int viewport[4]) {
    return 2.0f * (pixelX - viewport[0]) / std::max(viewport[2], 1) - 1.0f;
}
inline float ToNdcY(float pixelY, const int viewport[4]) {
    return 2.0f * (pixelY - viewport[1]) / std::max(viewport[3], 1) - 1.0f;
}

inline PlotArea InnerArea(const ChartRect& area, const ChartStyle& style, bool hasTitle) {
    return AxisLayout::Calculate(area, style, hasTitle);
}

inline std::vector<float> Axes(const PlotArea& plot, const int viewport[4], float zeroY) {
    return {
        ToNdcX(plot.left, viewport), ToNdcY(plot.bottom, viewport),
        ToNdcX(plot.left, viewport), ToNdcY(plot.top, viewport),
        ToNdcX(plot.left, viewport), ToNdcY(zeroY, viewport),
        ToNdcX(plot.right, viewport), ToNdcY(zeroY, viewport)
    };
}

inline std::vector<float> Grid(const PlotArea& plot, const int viewport[4], int divisions) {
    std::vector<float> vertices;
    divisions = std::max(divisions, 1);
    vertices.reserve(static_cast<std::size_t>(divisions - 1) * 8);
    for (int i = 1; i < divisions; ++i) {
        const float t = static_cast<float>(i) / static_cast<float>(divisions);
        const float x = plot.left + t * (plot.right - plot.left);
        const float y = plot.bottom + t * (plot.top - plot.bottom);
        vertices.insert(vertices.end(), {
            ToNdcX(x, viewport), ToNdcY(plot.bottom, viewport),
            ToNdcX(x, viewport), ToNdcY(plot.top, viewport),
            ToNdcX(plot.left, viewport), ToNdcY(y, viewport),
            ToNdcX(plot.right, viewport), ToNdcY(y, viewport)
        });
    }
    return vertices;
}

inline void DrawLabels(crocker::engine::Canvas2D& canvas, const ChartRect& area,
                       const PlotArea& plot, const int viewport[4], const ChartStyle& style,
                       const std::string& title, const std::string& xTitle, const std::string& yTitle) {
    (void)viewport;
    const auto color = style.textColor;
    if (style.showTitle && !title.empty()) {
        canvas.DrawText(title, (plot.left + plot.right) * 0.5f,
            area.y + area.height - style.titleMargin * 0.5f, style.titleSize,
            false, color, 1.0f, style.fontPath);
    }
    if (style.showAxisTitles && !xTitle.empty()) {
        canvas.DrawText(xTitle, (plot.left + plot.right) * 0.5f,
            area.y + style.bottomMargin * 0.35f, style.axisTitleSize,
            false, color, 1.0f, style.fontPath);
    }
    if (style.showAxisTitles && !yTitle.empty()) {
        canvas.DrawText(yTitle, area.x + style.leftMargin * 0.25f,
            (plot.bottom + plot.top) * 0.5f, style.axisTitleSize,
            true, color, 1.0f, style.fontPath);
    }
}

inline float Normalize(float value, float minimum, float maximum) {
    return maximum == minimum ? 0.5f : (value - minimum) / (maximum - minimum);
}

} // namespace chart_geometry
