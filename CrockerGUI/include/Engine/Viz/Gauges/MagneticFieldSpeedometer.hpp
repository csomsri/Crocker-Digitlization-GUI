#pragma once

#include "Engine/Viz/Charts/ChartRect.hpp"

#include <glad/glad.h>

#include <string>
#include <vector>

class MagneticFieldSpeedometer {
public:
    ~MagneticFieldSpeedometer();

    MagneticFieldSpeedometer() = default;
    MagneticFieldSpeedometer(const MagneticFieldSpeedometer&) = delete;
    MagneticFieldSpeedometer& operator=(const MagneticFieldSpeedometer&) = delete;

    bool SetValues(float targetValue, float actualValue, float maximumValue, std::string channelName);
    bool SetStatus(bool convergedValue, float errorValue, float toleranceValue,
                   float convergenceSecondsValue, bool timingActiveValue);
    void Render(int width, int height);

private:
    struct Point {
        float x;
        float y;
    };

    void EnsureOpenGLResources();
    float ClampValue(float value) const;
    float AngleForValue(float value) const;
    Point Polar(Point center, float radius, float degrees) const;
    void DrawArc(Point center, float radius, float startValue, float endValue,
                 float red, float green, float blue, float alpha);
    void DrawLine(Point start, Point end, float red, float green, float blue, float alpha);
    void DrawSegments(const std::vector<Point>& points, float red, float green, float blue, float alpha);
    void DrawVertices(const std::vector<float>& vertices, GLenum mode,
                      float red, float green, float blue, float alpha);
    void DrawNeedle(Point center, float radius);
    void DrawTargetMarker(Point center, float radius);
    void DrawText(const std::string& text, float centerX, float centerY, float scale,
                  float red, float green, float blue, float alpha);

    float target = 0.0f;
    float actual = 0.0f;
    float maximum = 1000.0f;
    float error = 0.0f;
    float tolerance = 0.5f;
    float convergenceSeconds = 0.0f;
    bool converged = true;
    bool timingActive = false;
    std::string channel = "TC1";
    GLuint vertexArray = 0;
    GLuint vertexBuffer = 0;
    GLuint shaderProgram = 0;
    GLint colorUniform = -1;
    GLint viewport[4] { 0, 0, 1, 1 };
};
