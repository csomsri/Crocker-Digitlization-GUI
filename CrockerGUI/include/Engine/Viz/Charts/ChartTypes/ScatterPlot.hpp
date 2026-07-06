#pragma once

#include "Engine/Viz/Charts/Chart.hpp"

#include <glad/glad.h>

class ScatterPlot : public Chart {
public:
    ~ScatterPlot() override;

    ScatterPlot() = default;
    ScatterPlot(const ScatterPlot&) = delete;
    ScatterPlot& operator=(const ScatterPlot&) = delete;

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
