#pragma once
#include <vector>
namespace crocker::engine {
// Widths include swatches/gaps and are measured by the same TextLayout used
// for drawing. Offsets are computed once instead of rescanning each prefix.
struct LegendLayout {
    std::vector<float> offsets;
    float totalWidth = 0;
    explicit LegendLayout(const std::vector<float>& widths) {
        for (float width : widths) { offsets.push_back(totalWidth); totalWidth += width; }
    }
};
}
