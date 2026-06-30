#pragma once

#include "Engine/Viz/Charts/Chart.hpp"

class LineChart : public Chart {
public:
    void SetData(const DataTable& data) override;
    void Update(float dt) override;
    void Render(const ChartRect& area) override;    
};