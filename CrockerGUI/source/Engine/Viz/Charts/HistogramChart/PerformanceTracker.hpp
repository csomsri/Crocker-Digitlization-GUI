#pragma once

#include <chrono>
#include <vector>
#include <numeric>
#include <string>
#include <sstream>
#include <iomanip>
#include <glad/glad.h>

class PerformanceTracker {
public:
    explicit PerformanceTracker(std::size_t sampleWindow = 60)
        : m_sampleWindow(sampleWindow) {
        glGenQueries(2, m_gpuQueries);
    }

    ~PerformanceTracker() {
        glDeleteQueries(2, m_gpuQueries);
    }

    // --- CPU Timer ---
    void BeginCpu() {
        m_cpuStart = std::chrono::high_resolution_clock::now();
    }

    void EndCpu() {
        auto now = std::chrono::high_resolution_clock::now();
        double durationMs = std::chrono::duration<double, std::milli>(now - m_cpuStart).count();
        AddSample(m_cpuSamples, durationMs);
    }

    // --- GPU Timer ---
    void BeginGpu() {
        glBeginQuery(GL_TIME_ELAPSED, m_gpuQueries[m_currentQuery]);
    }

    void EndGpu() {
        glEndQuery(GL_TIME_ELAPSED);

        GLuint prevQuery = m_gpuQueries[(m_currentQuery + 1) % 2];
        GLint available = 0;
        glGetQueryObjectiv(prevQuery, GL_QUERY_RESULT_AVAILABLE, &available);

        if (available) {
            GLuint64 timeNs = 0;
            glGetQueryObjectui64v(prevQuery, GL_QUERY_RESULT, &timeNs);
            double durationMs = static_cast<double>(timeNs) / 1000000.0;
            AddSample(m_gpuSamples, durationMs);
        }

        m_currentQuery = (m_currentQuery + 1) % 2;
    }

    // --- Frame FPS ---
    void FrameTick() {
        auto now = std::chrono::high_resolution_clock::now();
        if (m_lastFrameTime.time_since_epoch().count() > 0) {
            double frameTimeMs = std::chrono::duration<double, std::milli>(now - m_lastFrameTime).count();
            AddSample(m_frameSamples, frameTimeMs);
        }
        m_lastFrameTime = now;
    }

    // --- Metrics Accessors ---
    double GetFps() const {
        double avgFrameMs = GetAverage(m_frameSamples);
        return avgFrameMs > 0.0 ? (1000.0 / avgFrameMs) : 0.0;
    }

    double GetCpuTimeMs() const { return GetAverage(m_cpuSamples); }
    double GetGpuTimeMs() const { return GetAverage(m_gpuSamples); }
    double GetTotalFrameTimeMs() const { return GetAverage(m_frameSamples); }

    std::string GetFormattedSummary() const {
        std::ostringstream ss;
        ss << std::fixed << std::setprecision(2);
        ss << "FPS: " << GetFps() 
           << " | CPU: " << GetCpuTimeMs() << " ms"
           << " | GPU: " << GetGpuTimeMs() << " ms"
           << " | Total: " << GetTotalFrameTimeMs() << " ms";
        return ss.str();
    }

private:
    void AddSample(std::vector<double>& container, double value) {
        container.push_back(value);
        if (container.size() > m_sampleWindow) {
            container.erase(container.begin());
        }
    }

    double GetAverage(const std::vector<double>& container) const {
        if (container.empty()) return 0.0;
        double sum = std::accumulate(container.begin(), container.end(), 0.0);
        return sum / static_cast<double>(container.size());
    }

    std::size_t m_sampleWindow;
    std::chrono::high_resolution_clock::time_point m_cpuStart;
    std::chrono::high_resolution_clock::time_point m_lastFrameTime;

    std::vector<double> m_cpuSamples;
    std::vector<double> m_gpuSamples;
    std::vector<double> m_frameSamples;

    GLuint m_gpuQueries[2] = {0, 0};
    std::size_t m_currentQuery = 0;
};