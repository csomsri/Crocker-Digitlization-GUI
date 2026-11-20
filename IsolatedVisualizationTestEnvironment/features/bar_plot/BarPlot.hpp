#pragma once

struct BarTimings {
    float uploadMs;
    float kernelMs;
    float downloadMs;
};

#ifdef BAR_PLOT_CUDA
class BarPlotCuda {
public:
    BarPlotCuda(int device, int capacity);
    ~BarPlotCuda();
    BarPlotCuda(const BarPlotCuda&) = delete;
    BarPlotCuda& operator=(const BarPlotCuda&) = delete;

    void Run(const float* channels, int channelCount, float scale, float* heights,
             int count, BarTimings& timings);
    void DeviceId(char* id, int size) const;

private:
    struct Buffers;
    Buffers* buffers_;
};
#endif

// Shared math for the CPU baseline and the CUDA kernel.
#ifdef __CUDACC__
__host__ __device__
#endif
inline float BarHeight(float value, float scale) {
    const float fraction = value / scale;
    return fraction < -1.0f ? -1.0f : (fraction > 1.0f ? 1.0f : fraction);
}
