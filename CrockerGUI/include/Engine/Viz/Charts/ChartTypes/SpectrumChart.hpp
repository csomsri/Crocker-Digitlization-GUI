#pragma once

#include "Engine/Viz/Charts/ChartTypes/LineChart.hpp"

class SpectrumChart : public LineChart {
public:
    void SetData(const DataTable& data) override;

    void SetSampleRate(float value) noexcept;
    float GetSampleRate() const noexcept;

private:
    float sampleRate = 1.0f;
};
