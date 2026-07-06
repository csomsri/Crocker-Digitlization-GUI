#pragma once

#include "Engine/Viz/Charts/ChartTypes/BarChart.hpp"

#include <cstddef>

class HistogramChart : public BarChart {
public:
    void SetData(const DataTable& data) override;

    void SetBinCount(std::size_t value) noexcept;
    std::size_t GetBinCount() const noexcept;

private:
    std::size_t binCount = 20;
};
