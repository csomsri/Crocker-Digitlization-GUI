#pragma once

#include "Engine/Viz/Charts/Chart.hpp"

#include <glad/glad.h>
#include <chrono>
#include <cstddef>

class BarChart : public Chart {
public:
    ~BarChart() override;

    BarChart() = default;
    BarChart(const BarChart&) = delete;
    BarChart& operator=(const BarChart&) = delete;

    void SetData(const DataTable& data) override;
    void SetValueRange(float minimum, float maximum);
    void ClearValueRange();
    void Update(float dt) override;
    void Render(const ChartRect& area) override;

    // Performance metrics
    float GetFPS() const { return fps; }
    double GetSetDataTimeMs() const { return setDataCpuMs; }
    double GetRenderCpuTimeMs() const { return renderCpuMs; }
    double GetRenderGpuTimeMs() const { return renderGpuMs; }

private:
    void EnsureOpenGLResources();

    DataTable table;
    bool hasValueRange = false;
    float rangeMinimum = 0.0f;
    float rangeMaximum = 1.0f;
    GLuint vertexArray = 0;
    GLuint vertexBuffer = 0;
    GLuint shaderProgram = 0;

    // Performance metrics
    std::chrono::high_resolution_clock::time_point lastFrameTime;
    
    float fps = 0.0f;
    int frameCount = 0;
    float fpsTimer = 0.0f;

    double setDataCpuMs = 0.0;
    double renderCpuMs = 0.0;
    double renderGpuMs = 0.0;

    GLuint gpuQueries[2] = {0, 0};
    std::size_t currentQueryIdx = 0;
    bool queriesInitialized = false;
};