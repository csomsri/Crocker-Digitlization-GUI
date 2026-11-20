# Bar plot

Each backend receives up to 14 trim-channel values from the same Crocker packet decoder. It divides each value by the maximum absolute channel value and clamps to the signed display range. Zero is centered. Larger workloads repeat the same channel pattern, and all three configurations draw every requested bar.

The C++ CPU loop and CUDA kernel share the same native math. CUDA owns reusable device buffers and events. Each update uploads the channels, computes the heights, and copies them back before the shared OpenGL upload. During warm-up, the first rendered CUDA frame is checked against C++ CPU output.

See [results](results/README.md) for the output layout.
