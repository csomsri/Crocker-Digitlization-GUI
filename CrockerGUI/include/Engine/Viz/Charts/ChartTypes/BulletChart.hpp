#pragma once

#include "Engine/Viz/Charts/Chart.hpp"

#include <glad/glad.h>

class BulletChart : public Chart {
public:
    ~BulletChart() override;
    BulletChart() = default;
    BulletChart(const BulletChart&) = delete;
    BulletChart& operator=(const BulletChart&) = delete;

    void SetData(const DataTable& data) override;
    void Render(const ChartRect& area) override;

private:
    void EnsureOpenGLResources();

    DataTable table;
    GLuint vertexArray = 0;
    GLuint vertexBuffer = 0;
    GLuint shaderProgram = 0;
};
