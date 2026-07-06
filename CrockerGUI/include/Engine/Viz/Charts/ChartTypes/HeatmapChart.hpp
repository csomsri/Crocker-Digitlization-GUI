#pragma once

#include "Engine/Viz/Charts/Chart.hpp"

#include <glad/glad.h>

class HeatmapChart : public Chart {
public:
    ~HeatmapChart() override;
    HeatmapChart() = default;
    HeatmapChart(const HeatmapChart&) = delete;
    HeatmapChart& operator=(const HeatmapChart&) = delete;

    void SetData(const DataTable& data) override;
    void Render(const ChartRect& area) override;

private:
    void EnsureOpenGLResources();

    DataTable table;
    GLuint vertexArray = 0;
    GLuint vertexBuffer = 0;
    GLuint shaderProgram = 0;
};
