#pragma once
#include <memory>
#include <string>
#include <vector>
namespace crocker::engine {
class TimeDomainLinePlot {
public:
    TimeDomainLinePlot(bool coilResponse = false);
    ~TimeDomainLinePlot();
    void SetSamples(const std::vector<std::vector<float>>& samples);
    void Render(int width, int height, float pixelRatio = 1);
    void ReleaseResources();
private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
class MagneticFieldBarPlot {
public:
    MagneticFieldBarPlot();
    ~MagneticFieldBarPlot();
    void SetData(const std::string& title, const std::vector<std::string>& labels, const std::vector<float>& values);
    void Render(int width, int height, float pixelRatio = 1);
    void ReleaseResources();
private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
class MagneticFieldLinePlot {
public:
    MagneticFieldLinePlot();
    ~MagneticFieldLinePlot();
    void SetData(const std::string& title, const std::vector<std::string>& labels, const std::vector<std::vector<float>>& samples);
    void Render(int width, int height, float pixelRatio = 1);
    void ReleaseResources();
private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
}
