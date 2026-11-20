#include <cuda_runtime.h>

#include "BarPlot.hpp"

#include <chrono>
#include <memory>
#include <stdexcept>
#include <string>

namespace {
using Clock = std::chrono::steady_clock;

float Milliseconds(Clock::time_point start) {
    return std::chrono::duration<float, std::milli>(Clock::now() - start).count();
}

void Check(cudaError_t status, const char* operation) {
    if (status != cudaSuccess) {
        throw std::runtime_error(std::string(operation) + ": " + cudaGetErrorString(status));
    }
}

__global__ void PrepareBars(const float* channels, int channelCount, float scale,
                            float* heights, int count) {
    const int index = blockIdx.x * blockDim.x + threadIdx.x;
    if (index < count) {
        heights[index] = BarHeight(channels[index % channelCount], scale);
    }
}
}

struct BarPlotCuda::Buffers {
    int device;
    float* channels = nullptr;
    float* heights = nullptr;
    cudaEvent_t start = nullptr;
    cudaEvent_t end = nullptr;

    explicit Buffers(int ordinal) : device(ordinal) {}

    ~Buffers() {
        if (start) cudaEventDestroy(start);
        if (end) cudaEventDestroy(end);
        if (channels) cudaFree(channels);
        if (heights) cudaFree(heights);
    }
};

BarPlotCuda::BarPlotCuda(int device, int capacity) {
    Check(cudaSetDevice(device), "Selecting CUDA device");
    auto buffers = std::make_unique<Buffers>(device);
    Check(cudaMalloc(&buffers->channels, 14 * sizeof(float)), "Allocating input");
    Check(cudaMalloc(&buffers->heights, capacity * sizeof(float)), "Allocating output");
    Check(cudaEventCreate(&buffers->start), "Creating start event");
    Check(cudaEventCreate(&buffers->end), "Creating end event");
    buffers_ = buffers.release();
}

BarPlotCuda::~BarPlotCuda() {
    delete buffers_;
}

void BarPlotCuda::DeviceId(char* id, int size) const {
    Check(cudaDeviceGetPCIBusId(id, size, buffers_->device), "Reading CUDA device PCI ID");
}

void BarPlotCuda::Run(const float* channels, int channelCount, float scale,
                      float* heights, int count, BarTimings& timings) {
    auto started = Clock::now();
    Check(cudaMemcpy(buffers_->channels, channels, channelCount * sizeof(float),
                     cudaMemcpyHostToDevice), "Uploading channels");
    timings.uploadMs = Milliseconds(started);

    constexpr int blockSize = 256;
    Check(cudaEventRecord(buffers_->start), "Recording kernel start");
    PrepareBars<<<(count + blockSize - 1) / blockSize, blockSize>>>(
        buffers_->channels, channelCount, scale, buffers_->heights, count);
    Check(cudaGetLastError(), "Launching bar kernel");
    Check(cudaEventRecord(buffers_->end), "Recording kernel end");
    Check(cudaEventSynchronize(buffers_->end), "Waiting for bar kernel");
    Check(cudaEventElapsedTime(&timings.kernelMs, buffers_->start, buffers_->end),
          "Reading kernel timing");

    started = Clock::now();
    Check(cudaMemcpy(heights, buffers_->heights, count * sizeof(float),
                     cudaMemcpyDeviceToHost), "Downloading bars");
    timings.downloadMs = Milliseconds(started);
}
