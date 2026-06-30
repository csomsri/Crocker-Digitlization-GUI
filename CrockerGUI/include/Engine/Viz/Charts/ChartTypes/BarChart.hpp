#pragma once

#include "Engine/Viz/Charts/Chart.hpp"

#include <glad/glad.h>

class BarChart : public Chart {
public:
    ~BarChart() override;

    BarChart() = default;
    BarChart(const BarChart&) = delete;
    BarChart& operator=(const BarChart&) = delete;

    void SetData(const DataTable& data) override;
    void Update(float dt) override;
    void Render(const ChartRect& area) override;

private:
    void EnsureOpenGLResources();

    DataTable table;
    GLuint vertexArray = 0;
    GLuint vertexBuffer = 0;
    GLuint shaderProgram = 0;
};
