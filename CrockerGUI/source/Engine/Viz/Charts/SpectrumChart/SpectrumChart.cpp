#include "Engine/Viz/Charts/ChartTypes/SpectrumChart.hpp"

#include <cmath>
#include <numbers>

void SpectrumChart::SetData(const DataTable& data) {
    if (data.rows.empty() || data.ColumnCount() == 0) {
        LineChart::SetData({});
        return;
    }

    const std::size_t sampleCount = data.rows.size();
    const std::size_t frequencyCount = sampleCount / 2 + 1;
    DataTable spectrum;
    spectrum.columnNames = { "Frequency", "Magnitude" };
    spectrum.rows.reserve(frequencyCount);

    for (std::size_t frequency = 0; frequency < frequencyCount; ++frequency) {
        double real = 0.0;
        double imaginary = 0.0;
        for (std::size_t sample = 0; sample < sampleCount; ++sample) {
            const double angle = -2.0 * std::numbers::pi * static_cast<double>(frequency * sample)
                / static_cast<double>(sampleCount);
            real += static_cast<double>(data.rows[sample][0]) * std::cos(angle);
            imaginary += static_cast<double>(data.rows[sample][0]) * std::sin(angle);
        }
        const float hertz = static_cast<float>(frequency) * sampleRate / static_cast<float>(sampleCount);
        const float magnitude = static_cast<float>(2.0 * std::sqrt(real * real + imaginary * imaginary)
            / static_cast<double>(sampleCount));
        spectrum.rows.push_back({ hertz, magnitude });
    }
    LineChart::SetData(spectrum);
}

void SpectrumChart::SetSampleRate(float value) noexcept { sampleRate = value; }
float SpectrumChart::GetSampleRate() const noexcept { return sampleRate; }
