/*
    This is a Virtual Class
*/

#pragma once
#include "Engine/Graphics/Canvas2D.hpp"

#include "Engine/Visualization/Data/DataTable.hpp"
#include "Engine/Visualization/Charts/ChartRect.hpp"
#include "Engine/Visualization/Charts/ChartStyle.hpp"

#include <string>
#include <utility>

class Chart {
public:
    virtual ~Chart() = default;
    virtual void SetData(const DataTable& data) = 0;
    virtual void Update(float dt) { (void)dt; }
    virtual void Render(const ChartRect& area) = 0;

    void SetStyle(const ChartStyle& value) { style = value; }
    const ChartStyle& GetStyle() const noexcept { return style; }

    void SetTitle(std::string value) { title = std::move(value); }
    void SetAxisTitles(std::string xValue, std::string yValue) {
        xAxisTitle = std::move(xValue);
        yAxisTitle = std::move(yValue);
    }

    const std::string& GetTitle() const noexcept { return title; }
    const std::string& GetXAxisTitle() const noexcept { return xAxisTitle; }
    const std::string& GetYAxisTitle() const noexcept { return yAxisTitle; }

    void ReleaseResources() { context.Release(); }
    void RequireContext() { context.RequireCurrent(); }
    void SetPixelRatio(float ratio) { context.SetPixelRatio(ratio); }
    crocker::engine::Canvas2D& GetCanvas() { return canvas; }

protected:
    crocker::engine::RenderContext context;
    crocker::engine::Canvas2D canvas{context};
    ChartStyle style;
    std::string title;
    std::string xAxisTitle;
    std::string yAxisTitle;
};
