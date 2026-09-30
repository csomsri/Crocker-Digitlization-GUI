#pragma once

#include "Engine/Visualization/Charts/Chart.hpp"

class StarPlot : public Chart {
public:
    ~StarPlot() override = default;
    StarPlot() = default;
    StarPlot(const StarPlot&) = delete;
    StarPlot& operator=(const StarPlot&) = delete;

    void SetData(const DataTable& data) override;
    void Render(const ChartRect& area) override;

private:

    DataTable table;
};
