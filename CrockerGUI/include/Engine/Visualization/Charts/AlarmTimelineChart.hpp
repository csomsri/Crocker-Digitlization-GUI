#pragma once

#include "Engine/Visualization/Charts/Chart.hpp"

class AlarmTimelineChart : public Chart {
public:
    ~AlarmTimelineChart() override = default;
    AlarmTimelineChart() = default;
    AlarmTimelineChart(const AlarmTimelineChart&) = delete;
    AlarmTimelineChart& operator=(const AlarmTimelineChart&) = delete;

    void SetData(const DataTable& data) override;
    void Render(const ChartRect& area) override;

private:

    DataTable table;
};
