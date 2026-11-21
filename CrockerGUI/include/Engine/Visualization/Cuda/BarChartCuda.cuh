#pragma once

namespace crocker::cuda {

struct ViewportParams {
    int x, y, width, height;
};

bool IsDeviceAvailable();

void GenerateBarVertices(
    const float* d_values, float* d_vertices, int numBars,
    float plotLeft, float plotBottom, float plotTop,
    float minimum, float maximum, float zeroY,
    float slotWidth, float gap, ViewportParams vp
);

} // namespace crocker::cuda