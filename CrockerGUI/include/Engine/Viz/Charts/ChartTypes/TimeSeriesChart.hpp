#pragma once

#include "Engine/Viz/Charts/ChartTypes/LineChart.hpp"

#include <cstddef>

class TimeSeriesChart : public LineChart {
public:
    void SetData(const DataTable& data) override;

    void SetMaximumPoints(std::size_t value) noexcept;
    std::size_t GetMaximumPoints() const noexcept;

private:
    std::size_t maximumPoints = 1000;
};
