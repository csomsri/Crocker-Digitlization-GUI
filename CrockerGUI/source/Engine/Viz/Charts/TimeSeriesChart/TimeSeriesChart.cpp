#include "Engine/Viz/Charts/ChartTypes/TimeSeriesChart.hpp"

#include <algorithm>

void TimeSeriesChart::SetData(const DataTable& data) {
    if (maximumPoints == 0 || data.rows.size() <= maximumPoints) {
        LineChart::SetData(data);
        return;
    }

    DataTable visibleData;
    visibleData.columnNames = data.columnNames;
    visibleData.rows.assign(data.rows.end() - static_cast<std::ptrdiff_t>(maximumPoints), data.rows.end());
    LineChart::SetData(visibleData);
}

void TimeSeriesChart::SetMaximumPoints(std::size_t value) noexcept {
    maximumPoints = value;
}

std::size_t TimeSeriesChart::GetMaximumPoints() const noexcept {
    return maximumPoints;
}
