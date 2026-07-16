#include "Engine/Viz/Gauges/MagneticFieldSpeedometer.hpp"

#include "Engine/Viz/Data/DataTable.hpp"

#include "../../Charts/ChartOpenGL.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <utility>
#include <vector>

namespace {
constexpr float kPi = 3.14159265358979323846f;
constexpr float kStartAngle = 255.0f;
constexpr float kSweepAngle = 330.0f;

std::vector<float> rect(float left, float bottom, float right, float top, const GLint viewport[4])
{
    const float x0 = chart_gl::ToNdcX(left, viewport);
    const float x1 = chart_gl::ToNdcX(right, viewport);
    const float y0 = chart_gl::ToNdcY(bottom, viewport);
    const float y1 = chart_gl::ToNdcY(top, viewport);
    return { x0, y0, x1, y0, x1, y1, x0, y0, x1, y1, x0, y1 };
}

std::string fixed(float value, int precision)
{
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(precision) << value;
    return stream.str();
}
} // namespace

MagneticFieldSpeedometer::~MagneticFieldSpeedometer()
{
    chart_gl::DestroyResources(vertexArray, vertexBuffer, shaderProgram);
}

bool MagneticFieldSpeedometer::SetValues(float targetValue, float actualValue, float maximumValue, std::string channelName)
{
    const float nextMaximum = std::max(maximumValue, 1.0f);
    const float previousMaximum = maximum;
    maximum = nextMaximum;

    const float nextTarget = ClampValue(targetValue);
    const float nextActual = ClampValue(actualValue);
    const bool changed =
        std::abs(nextTarget - target) >= 0.05f ||
        std::abs(nextActual - actual) >= 0.05f ||
        std::abs(nextMaximum - previousMaximum) >= 0.05f ||
        channel != channelName;

    if (!changed) {
        return false;
    }

    target = nextTarget;
    actual = nextActual;
    channel = std::move(channelName);
    return true;
}

bool MagneticFieldSpeedometer::SetStatus(bool convergedValue, float errorValue, float toleranceValue,
                                         float convergenceSecondsValue, bool timingActiveValue)
{
    const float nextError = std::isfinite(errorValue) ? errorValue : 0.0f;
    const float nextTolerance = std::max(std::isfinite(toleranceValue) ? toleranceValue : 0.5f, 0.0f);
    const float nextSeconds = std::max(std::isfinite(convergenceSecondsValue) ? convergenceSecondsValue : 0.0f, 0.0f);
    const bool changed =
        converged != convergedValue ||
        timingActive != timingActiveValue ||
        std::abs(error - nextError) >= 0.05f ||
        std::abs(tolerance - nextTolerance) >= 0.01f ||
        std::abs(convergenceSeconds - nextSeconds) >= 0.05f;

    if (!changed) {
        return false;
    }

    converged = convergedValue;
    timingActive = timingActiveValue;
    error = nextError;
    tolerance = nextTolerance;
    convergenceSeconds = nextSeconds;
    return true;
}

void MagneticFieldSpeedometer::Render(int width, int height)
{
    const int safeWidth = std::max(width, 1);
    const int safeHeight = std::max(height, 1);
    glViewport(0, 0, safeWidth, safeHeight);
    glGetIntegerv(GL_VIEWPORT, viewport);
    EnsureOpenGLResources();

    glDisable(GL_DEPTH_TEST);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);

    const float w = static_cast<float>(safeWidth);
    const float h = static_cast<float>(safeHeight);
    const bool drawBackgroundBands = false;
    if (drawBackgroundBands) {
        DrawVertices(rect(0.0f, 0.0f, w, h, viewport), GL_TRIANGLES, 0.02f, 0.04f, 0.10f, 1.0f);
        DrawVertices(rect(0.0f, h * 0.56f, w, h, viewport), GL_TRIANGLES, 0.10f, 0.02f, 0.17f, 0.66f);
        DrawVertices(rect(0.0f, 0.0f, w, h * 0.33f, viewport), GL_TRIANGLES, 0.02f, 0.14f, 0.16f, 0.58f);
    }
    const bool drawBackgroundOverlays = false;
    if (drawBackgroundOverlays) {
        DrawVertices(rect(w * 0.12f, h * 0.06f, w * 0.88f, h * 0.25f, viewport), GL_TRIANGLES,
                     0.02f, 0.05f, 0.10f, 0.72f);
        DrawVertices(rect(w * 0.28f, h * 0.36f, w * 0.72f, h * 0.82f, viewport), GL_TRIANGLES,
                     0.0f, 0.75f, 1.0f, 0.055f);
        DrawVertices(rect(w * 0.36f, h * 0.28f, w * 0.64f, h * 0.72f, viewport), GL_TRIANGLES,
                     1.0f, 0.0f, 0.74f, 0.055f);
    }

    const float usable = std::min(w * 0.82f, h * 1.02f);
    const float radius = std::max(42.0f, usable * 0.36f);
    const Point center { w * 0.50f, h * 0.37f + radius * 0.30f };

    const bool drawGridLines = false;
    if (drawGridLines) {
        std::vector<Point> horizonSegments;
        horizonSegments.reserve(14);
        for (int i = 0; i < 7; ++i) {
            const float y = h * (0.74f + static_cast<float>(i) * 0.035f);
            horizonSegments.push_back({ w * 0.10f, y });
            horizonSegments.push_back({ w * 0.90f, y });
        }
        DrawSegments(horizonSegments, 0.0f, 0.86f, 1.0f, 0.14f);

        std::vector<Point> perspectiveSegments;
        perspectiveSegments.reserve(26);
        for (int i = -6; i <= 6; ++i) {
            const float lane = static_cast<float>(i);
            perspectiveSegments.push_back({ center.x + lane * w * 0.055f, h * 0.74f });
            perspectiveSegments.push_back({ center.x + lane * w * 0.012f, h * 0.54f });
        }
        DrawSegments(perspectiveSegments, 1.0f, 0.0f, 0.74f, 0.13f);
    }

    for (float offset : { 13.0f, 6.0f }) {
        DrawArc(center, radius * 1.04f + offset, 0.0f, maximum, 0.0f, 0.90f, 1.0f, 0.16f);
        DrawArc(center, radius + offset, 0.0f, actual, 1.0f, 0.0f, 0.80f, 0.20f);
        DrawArc(center, radius * 0.93f - offset * 0.12f, 0.0f, target, 1.0f, 0.78f, 0.10f, 0.18f);
    }
    DrawArc(center, radius * 1.04f, 0.0f, maximum, 0.0f, 0.96f, 1.0f, 1.0f);
    DrawArc(center, radius * 0.93f, 0.0f, target, 1.0f, 0.78f, 0.10f, 1.0f);
    DrawArc(center, radius, 0.0f, actual, 1.0f, 0.0f, 0.80f, 1.0f);

    std::vector<Point> minorTicks;
    std::vector<Point> majorTicks;
    minorTicks.reserve(32);
    majorTicks.reserve(10);
    for (int value = 0; value <= 1000; value += 50) {
        const bool major = value % 250 == 0;
        const float angle = AngleForValue(static_cast<float>(value));
        const float inner = radius * (major ? 0.80f : 0.91f);
        const auto a = Polar(center, radius * 1.02f, angle);
        const auto b = Polar(center, inner, angle);
        if (major) {
            majorTicks.push_back(a);
            majorTicks.push_back(b);
        } else {
            minorTicks.push_back(a);
            minorTicks.push_back(b);
        }
    }
    DrawSegments(minorTicks, 1.0f, 0.0f, 0.74f, 0.45f);
    DrawSegments(majorTicks, 0.86f, 1.0f, 1.0f, 0.95f);

    for (int value : { 0, 250, 500, 750, 1000 }) {
        const float angle = AngleForValue(static_cast<float>(value));
        const float labelRadius = value == 500 ? radius * 0.50f : radius * 0.70f;
        auto labelPoint = Polar(center, labelRadius, angle);
        if (value == 0 || value == 1000) {
            labelPoint.y += radius * 0.035f;
        }
        DrawText(std::to_string(value), labelPoint.x, labelPoint.y,
                 std::clamp(radius * 0.0145f, 1.4f, 2.4f), 0.88f, 0.99f, 1.0f, 0.92f);
    }

    DrawTargetMarker(center, radius);
    DrawNeedle(center, radius);

    DrawText(channel + " FEEDBACK", w * 0.5f, h - 28.0f, std::clamp(w * 0.0042f, 1.7f, 2.8f),
             0.50f, 1.0f, 0.70f, 0.95f);
    const std::string convergenceText = std::string("CONVERGENCE ") + (converged ? "TRUE" : "FALSE");
    const std::string toleranceText = "+/- " + fixed(tolerance, 2) + " A";
    const std::string timeText = std::string("TIME ") + fixed(convergenceSeconds, 1) + " S" +
                                 (timingActive ? " RUN" : "");
    const std::string errorText = "ERROR " + fixed(error, 2) + " A";

    DrawText(convergenceText, w * 0.14f, h - 54.0f, std::clamp(radius * 0.012f, 1.2f, 2.1f),
             converged ? 0.48f : 1.0f, converged ? 1.0f : 0.24f, converged ? 0.66f : 0.22f, 0.92f);
    DrawText(toleranceText, w * 0.14f, h - 82.0f, std::clamp(radius * 0.010f, 1.0f, 1.7f),
             0.60f, 0.96f, 1.0f, 0.82f);
    DrawText(timeText, w * 0.14f, h - 108.0f, std::clamp(radius * 0.010f, 1.0f, 1.7f),
             1.0f, 0.72f, 0.16f, 0.88f);
    DrawText(errorText, w * 0.88f, h - 66.0f, std::clamp(radius * 0.012f, 1.2f, 2.1f),
             1.0f, 0.24f, 0.22f, 0.94f);

    DrawText("ACTUAL", w * 0.22f, h * 0.16f, std::clamp(radius * 0.014f, 1.3f, 2.2f),
             0.60f, 0.96f, 1.0f, 0.82f);
    DrawText(fixed(actual, 2), w * 0.22f, h * 0.085f, std::clamp(radius * 0.030f, 2.6f, 4.5f),
             1.0f, 0.0f, 0.74f, 0.95f);
    DrawText("TARGET", w * 0.78f, h * 0.16f, std::clamp(radius * 0.014f, 1.3f, 2.2f),
             1.0f, 0.72f, 0.16f, 0.82f);
    DrawText(fixed(target, 2), w * 0.78f, h * 0.085f, std::clamp(radius * 0.026f, 2.3f, 3.8f),
             1.0f, 0.72f, 0.16f, 0.90f);
}

void MagneticFieldSpeedometer::EnsureOpenGLResources()
{
    if (shaderProgram == 0) {
        chart_gl::CreateResources(vertexArray, vertexBuffer, shaderProgram);
        colorUniform = glGetUniformLocation(shaderProgram, "chartColor");
    }
}

float MagneticFieldSpeedometer::ClampValue(float value) const
{
    return std::clamp(std::isfinite(value) ? value : 0.0f, 0.0f, maximum);
}

float MagneticFieldSpeedometer::AngleForValue(float value) const
{
    return kStartAngle - kSweepAngle * (ClampValue(value) / maximum);
}

MagneticFieldSpeedometer::Point MagneticFieldSpeedometer::Polar(Point center, float radius, float degrees) const
{
    const float radians = degrees * kPi / 180.0f;
    return { center.x + std::cos(radians) * radius, center.y + std::sin(radians) * radius };
}

void MagneticFieldSpeedometer::DrawArc(Point center, float radius, float startValue, float endValue,
                                       float red, float green, float blue, float alpha)
{
    const float start = AngleForValue(startValue);
    const float end = AngleForValue(endValue);
    const int steps = std::max(14, static_cast<int>(std::abs(end - start) / 5.0f));
    std::vector<float> vertices;
    vertices.reserve(static_cast<std::size_t>(steps + 1) * 2);
    for (int i = 0; i <= steps; ++i) {
        const float t = static_cast<float>(i) / static_cast<float>(steps);
        const auto point = Polar(center, radius, start + (end - start) * t);
        vertices.push_back(chart_gl::ToNdcX(point.x, viewport));
        vertices.push_back(chart_gl::ToNdcY(point.y, viewport));
    }
    DrawVertices(vertices, GL_LINE_STRIP, red, green, blue, alpha);
}

void MagneticFieldSpeedometer::DrawLine(Point start, Point end, float red, float green, float blue, float alpha)
{
    const std::vector<float> vertices {
        chart_gl::ToNdcX(start.x, viewport), chart_gl::ToNdcY(start.y, viewport),
        chart_gl::ToNdcX(end.x, viewport), chart_gl::ToNdcY(end.y, viewport),
    };
    DrawVertices(vertices, GL_LINES, red, green, blue, alpha);
}

void MagneticFieldSpeedometer::DrawSegments(const std::vector<Point>& points, float red, float green, float blue, float alpha)
{
    std::vector<float> vertices;
    vertices.reserve(points.size() * 2);
    for (const Point& point : points) {
        vertices.push_back(chart_gl::ToNdcX(point.x, viewport));
        vertices.push_back(chart_gl::ToNdcY(point.y, viewport));
    }
    DrawVertices(vertices, GL_LINES, red, green, blue, alpha);
}

void MagneticFieldSpeedometer::DrawVertices(const std::vector<float>& vertices, GLenum mode,
                                            float red, float green, float blue, float alpha)
{
    if (vertices.empty()) return;

    glNamedBufferData(vertexBuffer,
        static_cast<GLsizeiptr>(vertices.size() * sizeof(float)),
        vertices.data(), GL_DYNAMIC_DRAW);
    glUseProgram(shaderProgram);
    glProgramUniform4f(shaderProgram, colorUniform, red, green, blue, alpha);
    glBindVertexArray(vertexArray);
    glDrawArrays(mode, 0, static_cast<GLsizei>(vertices.size() / 2));
}

void MagneticFieldSpeedometer::DrawNeedle(Point center, float radius)
{
    const float angle = AngleForValue(actual);
    const auto tip = Polar(center, radius * 0.84f, angle);
    const auto rear = Polar(center, radius * 0.20f, angle + 180.0f);
    const auto left = Polar(center, radius * 0.075f, angle + 105.0f);
    const auto right = Polar(center, radius * 0.075f, angle - 105.0f);
    const std::vector<float> blade {
        chart_gl::ToNdcX(tip.x, viewport), chart_gl::ToNdcY(tip.y, viewport),
        chart_gl::ToNdcX(left.x, viewport), chart_gl::ToNdcY(left.y, viewport),
        chart_gl::ToNdcX(rear.x, viewport), chart_gl::ToNdcY(rear.y, viewport),
        chart_gl::ToNdcX(tip.x, viewport), chart_gl::ToNdcY(tip.y, viewport),
        chart_gl::ToNdcX(rear.x, viewport), chart_gl::ToNdcY(rear.y, viewport),
        chart_gl::ToNdcX(right.x, viewport), chart_gl::ToNdcY(right.y, viewport),
    };
    DrawVertices(blade, GL_TRIANGLES, 1.0f, 0.0f, 0.74f, 0.88f);
    DrawLine(rear, tip, 0.0f, 0.92f, 1.0f, 0.95f);
    DrawVertices(rect(center.x - 5.0f, center.y - 5.0f, center.x + 5.0f, center.y + 5.0f, viewport),
                 GL_TRIANGLES, 0.95f, 1.0f, 1.0f, 0.95f);
}

void MagneticFieldSpeedometer::DrawTargetMarker(Point center, float radius)
{
    const float angle = AngleForValue(target);
    const auto outer = Polar(center, radius * 1.15f, angle);
    const auto inner = Polar(center, radius * 0.84f, angle);
    const auto sideA = Polar(outer, radius * 0.052f, angle + 112.0f);
    const auto sideB = Polar(outer, radius * 0.052f, angle - 112.0f);
    const std::vector<float> marker {
        chart_gl::ToNdcX(inner.x, viewport), chart_gl::ToNdcY(inner.y, viewport),
        chart_gl::ToNdcX(sideA.x, viewport), chart_gl::ToNdcY(sideA.y, viewport),
        chart_gl::ToNdcX(outer.x, viewport), chart_gl::ToNdcY(outer.y, viewport),
        chart_gl::ToNdcX(inner.x, viewport), chart_gl::ToNdcY(inner.y, viewport),
        chart_gl::ToNdcX(outer.x, viewport), chart_gl::ToNdcY(outer.y, viewport),
        chart_gl::ToNdcX(sideB.x, viewport), chart_gl::ToNdcY(sideB.y, viewport),
    };
    DrawVertices(marker, GL_TRIANGLES, 1.0f, 0.72f, 0.16f, 0.82f);
}

void MagneticFieldSpeedometer::DrawText(const std::string& text, float centerX, float centerY, float scale,
                                        float red, float green, float blue, float alpha)
{
    const auto vertices = chart_gl::Text(text, centerX, centerY, scale, false, viewport);
    DrawVertices(vertices, GL_TRIANGLES, red, green, blue, alpha);
}
