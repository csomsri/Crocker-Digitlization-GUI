#pragma once
#include <algorithm>
#include <cmath>
#include <stdexcept>
namespace crocker::engine {
struct Viewport {
    int width = 1, height = 1;
    float pixelRatio = 1;
    float LogicalWidth() const { return static_cast<float>(width) / pixelRatio; }
    float LogicalHeight() const { return static_cast<float>(height) / pixelRatio; }
    void Validate() const {
        if (width < 1 || height < 1 || !std::isfinite(pixelRatio) || pixelRatio <= 0)
            throw std::invalid_argument("Viewport dimensions and pixel ratio must be positive.");
    }
};
}
