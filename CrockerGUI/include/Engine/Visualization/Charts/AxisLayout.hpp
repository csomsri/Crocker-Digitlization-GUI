#pragma once
#include "Engine/Visualization/Charts/ChartRect.hpp"
#include "Engine/Visualization/Charts/ChartStyle.hpp"
#include <algorithm>
namespace chart_geometry {
struct PlotArea { float left, right, bottom, top; };
class AxisLayout {
public:
    static PlotArea Calculate(const ChartRect& area, const ChartStyle& style, bool hasTitle) {
        const float topMargin = hasTitle && style.showTitle ? style.titleMargin : style.plotPadding;
        return {area.x + style.leftMargin,
            area.x + std::max(area.width - style.plotPadding, style.leftMargin + 1),
            area.y + style.bottomMargin,
            area.y + std::max(area.height - topMargin, style.bottomMargin + 1)};
    }
};
}
