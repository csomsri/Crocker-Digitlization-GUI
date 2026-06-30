/*
    This is a Virtual Class
*/

#pragma once

#include "Engine/Viz/Data/DataTable.hpp"
#include "Engine/Viz/Charts/ChartRect.hpp"
#include "Engine/Viz/Charts/ChartStyle.hpp"


class Chart {
public:
    virtual ~Chart() = default;
    virtual void SetData(const DataTable& data) = 0;
    virtual void Update(float dt) { (void)dt; }
    virtual void Render(const ChartRect& area) = 0;

    void SetStyle(const ChartStyle& value) { style = value; }
    const ChartStyle& GetStyle() const noexcept { return style; }

protected:
    ChartStyle style;
};
