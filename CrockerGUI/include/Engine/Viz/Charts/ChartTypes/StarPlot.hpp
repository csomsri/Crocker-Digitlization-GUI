#pragma once

#include "Engine/Viz/Charts/Chart.hpp"

#include <glad/glad.h>

class StarPlot : public Chart {
public:
    ~StarPlot() override;
    StarPlot() = default;
    StarPlot(const StarPlot&) = delete;
    StarPlot& operator=(const StarPlot&) = delete;

    void SetData(const DataTable& data) override;
    void Render(const ChartRect& area) override;

private:
    void EnsureOpenGLResources();

    DataTable table;
    GLuint vertexArray = 0;
    GLuint vertexBuffer = 0;
    GLuint shaderProgram = 0;
};
