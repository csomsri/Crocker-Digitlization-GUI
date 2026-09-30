#pragma once

#include "Engine/Visualization/Charts/Chart.hpp"

class LineChart : public Chart {
public:
    ~LineChart() override = default;

    LineChart() = default;
    LineChart(const LineChart&) = delete;
    LineChart& operator=(const LineChart&) = delete;

    void SetData(const DataTable& data) override;
    void Update(float dt) override;
    void Render(const ChartRect& area) override;

private:

    DataTable table;
};
