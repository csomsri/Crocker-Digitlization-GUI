#pragma once

#include "Engine/Visualization/Charts/Chart.hpp"

class HeatmapChart : public Chart {
public:
    ~HeatmapChart() override = default;
    HeatmapChart() = default;
    HeatmapChart(const HeatmapChart&) = delete;
    HeatmapChart& operator=(const HeatmapChart&) = delete;

    void SetData(const DataTable& data) override;
    void Render(const ChartRect& area) override;

private:

    DataTable table;
};
