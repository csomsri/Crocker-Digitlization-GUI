#pragma once

#include "Engine/Visualization/Charts/Chart.hpp"

class BarChart : public Chart {
public:
    ~BarChart() override = default;

    BarChart() = default;
    BarChart(const BarChart&) = delete;
    BarChart& operator=(const BarChart&) = delete;

    void SetData(const DataTable& data) override;
    void SetValueRange(float minimum, float maximum);
    void ClearValueRange();
    void Update(float dt) override;
    void Render(const ChartRect& area) override;

private:

    DataTable table;
    bool hasValueRange = false;
    float rangeMinimum = 0.0f;
    float rangeMaximum = 1.0f;
};
