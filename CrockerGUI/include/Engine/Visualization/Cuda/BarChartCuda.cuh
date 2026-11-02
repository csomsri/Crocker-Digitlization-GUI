#pragma once

namespace crocker::cuda {

bool IsDeviceAvailable();

void GenerateBarVertices(
    const float* d_values, float* d_vertices, int numBars,
    float plotLeft, float plotBottom, float plotTop,
    float minimum, float maximum, float zeroY,
    float slotWidth, float gap, int vpX, int vpY, int vpW, int vpH
);

} // end of namespace crocker::cuda