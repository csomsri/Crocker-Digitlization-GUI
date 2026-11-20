#include "BarPlot.hpp"

#include <cstdio>
#include <exception>
#include <memory>

#ifdef _WIN32
#define BAR_API extern "C" __declspec(dllexport)
#else
#define BAR_API extern "C"
#endif

BAR_API void bar_cpu(const float* channels, int channelCount, float scale,
                     float* heights, int count) {
    for (int index = 0; index < count; ++index) {
        heights[index] = BarHeight(channels[index % channelCount], scale);
    }
}

BAR_API void* bar_cuda_create(int device, int capacity, char* id, int idSize,
                             char* error, int errorSize) {
#ifdef BAR_PLOT_CUDA
    try {
        auto plot = std::make_unique<BarPlotCuda>(device, capacity);
        plot->DeviceId(id, idSize);
        return plot.release();
    } catch (const std::exception& exception) {
        std::snprintf(error, errorSize, "%s", exception.what());
    }
#else
    std::snprintf(error, errorSize, "Built with BENCHMARK_ENABLE_CUDA=OFF");
#endif
    return nullptr;
}

BAR_API int bar_cuda_run(void* handle, const float* channels, int channelCount,
                         float scale, float* heights, int count, BarTimings* timings,
                         char* error, int errorSize) {
#ifdef BAR_PLOT_CUDA
    try {
        static_cast<BarPlotCuda*>(handle)->Run(channels, channelCount, scale, heights,
                                              count, *timings);
        return 1;
    } catch (const std::exception& exception) {
        std::snprintf(error, errorSize, "%s", exception.what());
    }
#else
    std::snprintf(error, errorSize, "Built with BENCHMARK_ENABLE_CUDA=OFF");
#endif
    return 0;
}

BAR_API void bar_cuda_destroy(void* handle) {
#ifdef BAR_PLOT_CUDA
    delete static_cast<BarPlotCuda*>(handle);
#endif
}
