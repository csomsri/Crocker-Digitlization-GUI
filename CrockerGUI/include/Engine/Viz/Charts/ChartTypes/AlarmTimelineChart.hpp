#pragma once

#include "Engine/Viz/Charts/Chart.hpp"

#include <glad/glad.h>

class AlarmTimelineChart : public Chart {
public:
    ~AlarmTimelineChart() override;
    AlarmTimelineChart() = default;
    AlarmTimelineChart(const AlarmTimelineChart&) = delete;
    AlarmTimelineChart& operator=(const AlarmTimelineChart&) = delete;

    void SetData(const DataTable& data) override;
    void Render(const ChartRect& area) override;

private:
    void EnsureOpenGLResources();

    DataTable table;
    GLuint vertexArray = 0;
    GLuint vertexBuffer = 0;
    GLuint shaderProgram = 0;
};
