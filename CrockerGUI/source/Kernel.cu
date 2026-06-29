#include <cuda_runtime.h>

__global__ void testKernel() {}

void onLaunchTestKernel() {
    testKernel<<<1, 1>>>();
}