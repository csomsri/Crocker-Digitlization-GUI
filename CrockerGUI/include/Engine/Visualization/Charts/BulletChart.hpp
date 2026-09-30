#pragma once

#include "Engine/Visualization/Charts/Chart.hpp"

class BulletChart : public Chart {
public:
    ~BulletChart() override = default;
    BulletChart() = default;
    BulletChart(const BulletChart&) = delete;
    BulletChart& operator=(const BulletChart&) = delete;

    void SetData(const DataTable& data) override;
    void Render(const ChartRect& area) override;

private:

    DataTable table;
};
