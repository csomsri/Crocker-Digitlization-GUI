#include "Engine/Visualization/Cuda/BarChartCuda.cuh"
#include <cuda_runtime.h>
#include <algorithm>

namespace crocker::cuda {

// Device helper to mimic chart_geometry::ToNdc
__device__ float ToNdc(float val, int vpStart, int vpSize) {
    return ((val - static_cast<float>(vpStart)) / static_cast<float>(vpSize)) * 2.0f - 1.0f;
}

__global__ void BarVertexKernel(
    const float* values, float* vertices, int numBars,
    float plotLeft, float plotBottom, float plotTop,
    float minimum, float maximum, float zeroY,
    float slotWidth, float gap, ViewportParams vp) 
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= numBars) return;

    // 1. Calculate world coordinates (mirrors BarChart.cpp lines 64-69)
    float x0 = plotLeft + static_cast<float>(i) * slotWidth + gap;
    float x1 = plotLeft + static_cast<float>(i + 1) * slotWidth - gap;
    
    // Normalize value
    float val = values[i];
    float normVal = (val - minimum) / (maximum - minimum); 
    float valueY = plotBottom + normVal * (plotTop - plotBottom);
    
    float y0 = min(zeroY, valueY);
    float y1 = max(zeroY, valueY);

    // 2. Convert to NDC (mirrors BarChart.cpp lines 71-74)
    float nx0 = ToNdc(x0, vp.x, vp.width);
    float nx1 = ToNdc(x1, vp.x, vp.width);
    float ny0 = ToNdc(y0, vp.y, vp.height);
    float ny1 = ToNdc(y1, vp.y, vp.height);

    // 3. Write 6 vertices (12 floats) to the output buffer
    int vIdx = i * 12;
    
    // Triangle 1
    vertices[vIdx + 0] = nx0; vertices[vIdx + 1] = ny0;
    vertices[vIdx + 2] = nx1; vertices[vIdx + 3] = ny0;
    vertices[vIdx + 4] = nx1; vertices[vIdx + 5] = ny1;
    
    // Triangle 2
    vertices[vIdx + 6] = nx0; vertices[vIdx + 7] = ny0;
    vertices[vIdx + 8] = nx1; vertices[vIdx + 9] = ny1;
    vertices[vIdx + 10]= nx0; vertices[vIdx + 11]= ny1;
}

void GenerateBarVertices(
    const float* d_values, float* d_vertices, int numBars,
    float plotLeft, float plotBottom, float plotTop,
    float minimum, float maximum, float zeroY,
    float slotWidth, float gap, ViewportParams viewport) 
{
    int threadsPerBlock = 256;
    int blocksPerGrid = (numBars + threadsPerBlock - 1) / threadsPerBlock;

    BarVertexKernel<<<blocksPerGrid, threadsPerBlock>>>(
        d_values, d_vertices, numBars,
        plotLeft, plotBottom, plotTop,
        minimum, maximum, zeroY,
        slotWidth, gap, viewport
    );
    
    cudaDeviceSynchronize();
}

} // namespace crocker::cuda