#pragma once

#include "Engine/Visualization/Charts/Chart.hpp"

class ScatterPlot : public Chart {
public:
    ~ScatterPlot() override = default;

    ScatterPlot() = default;
    ScatterPlot(const ScatterPlot&) = delete;
    ScatterPlot& operator=(const ScatterPlot&) = delete;

    void SetData(const DataTable& data) override;
    void Update(float dt) override;
    void Render(const ChartRect& area) override;

private:

    DataTable table;
};
