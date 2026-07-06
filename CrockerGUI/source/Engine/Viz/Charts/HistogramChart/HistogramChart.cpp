#include "Engine/Viz/Charts/ChartTypes/HistogramChart.hpp"

#include <algorithm>
#include <limits>

void HistogramChart::SetData(const DataTable& data) {
    if (data.rows.empty() || data.ColumnCount() == 0 || binCount == 0) {
        BarChart::SetData({});
        return;
    }

    float minimum = std::numeric_limits<float>::max();
    float maximum = std::numeric_limits<float>::lowest();
    for (const auto& row : data.rows) {
        minimum = std::min(minimum, row[0]);
        maximum = std::max(maximum, row[0]);
    }

    const float width = maximum == minimum ? 1.0f : (maximum - minimum) / static_cast<float>(binCount);
    std::vector<float> counts(binCount, 0.0f);
    for (const auto& row : data.rows) {
        const auto raw = static_cast<std::size_t>((row[0] - minimum) / width);
        counts[std::min(raw, binCount - 1)] += 1.0f;
    }

    DataTable histogram;
    histogram.columnNames = { "Bin", "Count" };
    histogram.rows.reserve(binCount);
    for (std::size_t bin = 0; bin < binCount; ++bin) {
        histogram.rows.push_back({ minimum + (static_cast<float>(bin) + 0.5f) * width, counts[bin] });
    }
    BarChart::SetData(histogram);
}

void HistogramChart::SetBinCount(std::size_t value) noexcept { binCount = value; }
std::size_t HistogramChart::GetBinCount() const noexcept { return binCount; }
