#include <cuda_runtime.h>

__global__ void testKernel() {}

void onLaunchTestKernel() {
    testKernel<<<1, 1>>>();
}

void compute_histogram(values, bins) {

}

void compute_linear(values, bins) {

}

int main() {
    

    return 0;
}