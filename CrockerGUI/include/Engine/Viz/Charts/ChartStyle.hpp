#pragma once

#include <vector>

struct ChartColor {
    float r;
    float g;
    float b;
};

struct ChartStyle {
    ChartColor lineColor { 0.10f, 0.72f, 0.95f };
    std::vector<ChartColor> lineColors {
        { 0.10f, 0.72f, 0.95f },
        { 0.95f, 0.42f, 0.30f },
        { 0.55f, 0.40f, 0.95f },
        { 0.95f, 0.74f, 0.20f },
        { 0.20f, 0.78f, 0.52f }
    };
    ChartColor barColor { 0.24f, 0.68f, 0.42f };
    ChartColor axisColor { 0.55f, 0.58f, 0.64f };
    ChartColor gridColor { 0.22f, 0.24f, 0.28f };
    ChartColor textColor { 0.82f, 0.84f, 0.88f };
    ChartColor heatLowColor { 0.10f, 0.20f, 0.55f };
    ChartColor heatHighColor { 0.95f, 0.25f, 0.12f };
    ChartColor normalColor { 0.20f, 0.72f, 0.38f };
    ChartColor warningColor { 0.96f, 0.68f, 0.16f };
    ChartColor alarmColor { 0.90f, 0.18f, 0.20f };

    float lineWidth = 2.0f;
    float axisWidth = 1.0f;
    float gridWidth = 1.0f;
    float pointRadius = 4.0f;
    float shadowOpacity = 0.18f;
    float titleSize = 3.0f;
    float axisTitleSize = 2.0f;
    float plotPadding = 14.0f;
    float leftMargin = 58.0f;
    float bottomMargin = 46.0f;
    float titleMargin = 30.0f;
    int gridDivisions = 5;

    bool showAxes = true;
    bool showGrid = true;
    bool showPoints = true;
    bool showLineShadow = true;
    bool showTitle = true;
    bool showAxisTitles = true;
};
