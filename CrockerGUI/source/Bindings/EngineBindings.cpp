#include "Bindings.hpp"

#include "Engine/Engine.hpp"
#include "Engine/Render/Renderer.hpp"
#include "Engine/Viz/Charts/ChartTypes/BarChart.hpp"
#include "Engine/Viz/Charts/ChartTypes/TimeSeriesChart.hpp"
#include "Engine/Viz/Text/FontRenderer.hpp"
#include "Engine/Viz/Gauges/MagneticFieldSpeedometer.hpp"

#include <pybind11/stl.h>

#include <algorithm>
#include <cstdint>
#include <iomanip>
#include <sstream>
#include <string>
#include <vector>

namespace py = pybind11;

namespace {
thread_local const py::function* currentGetProcAddress = nullptr;
constexpr std::size_t kMagneticVisibleSamples = 1800;

void* PythonGetProcAddress(const char* name)
{
    if (currentGetProcAddress == nullptr) return nullptr;
    py::gil_scoped_acquire gil;
    const py::object result = (*currentGetProcAddress)(name);
    if (result.is_none()) return nullptr;
    return reinterpret_cast<void*>(result.cast<std::uintptr_t>());
}

ChartStyle MagneticChartStyle()
{
    ChartStyle style;
    style.lineColors = {
        { 96.0f / 255.0f, 165.0f / 255.0f, 250.0f / 255.0f },
        { 34.0f / 255.0f, 197.0f / 255.0f, 94.0f / 255.0f },
        { 245.0f / 255.0f, 158.0f / 255.0f, 11.0f / 255.0f },
        { 244.0f / 255.0f, 114.0f / 255.0f, 182.0f / 255.0f },
    };
    style.lineColor = style.lineColors.front();
    style.barColor = style.lineColors.front();
    style.axisColor = { 126.0f / 255.0f, 144.0f / 255.0f, 168.0f / 255.0f };
    style.gridColor = { 51.0f / 255.0f, 65.0f / 255.0f, 85.0f / 255.0f };
    style.textColor = { 229.0f / 255.0f, 231.0f / 255.0f, 235.0f / 255.0f };
    style.showPoints = false;
    style.showLineShadow = false;
    style.gridDivisions = 4;
    style.leftMargin = 76.0f;
    style.bottomMargin = 66.0f;
    style.titleMargin = 58.0f;
    style.plotPadding = 22.0f;
    style.titleSize = 20.0f;
    style.axisTitleSize = 17.0f;
    style.tickLabelSize = 16.0f;
    style.legendSize = 16.0f;
    style.lineWidth = 2.4f;
    return style;
}

std::string FormatOneDecimal(float value)
{
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(1) << value;
    return stream.str();
}

void PrepareViewport(int width, int height)
{
    const int safeWidth = std::max(width, 1);
    const int safeHeight = std::max(height, 1);
    glViewport(0, 0, safeWidth, safeHeight);
    glDisable(GL_DEPTH_TEST);
    glEnable(GL_MULTISAMPLE);
    glEnable(GL_LINE_SMOOTH);
    glHint(GL_LINE_SMOOTH_HINT, GL_NICEST);
    glEnable(GL_BLEND);
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
    glClearColor(17.0f / 255.0f, 27.0f / 255.0f, 46.0f / 255.0f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
}

class TimeDomainLinePlot {
public:
    TimeDomainLinePlot()
    {
        ChartStyle style;
        style.lineColors = {
            { 53.0f / 255.0f, 244.0f / 255.0f, 1.0f },
            { 143.0f / 255.0f, 1.0f, 210.0f / 255.0f },
            { 1.0f, 81.0f / 255.0f, 105.0f / 255.0f },
        };
        style.axisColor = { 87.0f / 255.0f, 157.0f / 255.0f, 163.0f / 255.0f };
        style.gridColor = { 36.0f / 255.0f, 72.0f / 255.0f, 76.0f / 255.0f };
        style.textColor = { 216.0f / 255.0f, 253.0f / 255.0f, 1.0f };
        style.showPoints = false;
        style.showLineShadow = false;
        style.gridDivisions = 3;
        style.leftMargin = 54.0f;
        style.bottomMargin = 54.0f;
        style.titleMargin = 38.0f;
        chart.SetStyle(style);
        chart.SetTitle("");
        chart.SetAxisTitles("Time (s)", "");
        chart.SetMaximumPoints(kMagneticVisibleSamples);
    }

    void SetSamples(const std::vector<std::vector<float>>& samples)
    {
        DataTable data;
        data.columnNames = { "Time", "Actual", "Target", "Error" };
        data.rows = samples;
        if (!data.rows.empty()) {
            const float start = data.rows.front().front();
            for (auto& row : data.rows) {
                if (!row.empty()) row.front() -= start;
            }
        }
        chart.SetData(data);
    }

    void Render(int width, int height)
    {
        const int safeWidth = std::max(width, 1);
        const int safeHeight = std::max(height, 1);
        glViewport(0, 0, safeWidth, safeHeight);
        glDisable(GL_DEPTH_TEST);
        glEnable(GL_MULTISAMPLE);
        glEnable(GL_LINE_SMOOTH);
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST);
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glClearColor(3.0f / 255.0f, 8.0f / 255.0f, 8.0f / 255.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT);
        chart.Render({ 0.0f, 0.0f, static_cast<float>(safeWidth), static_cast<float>(safeHeight) });
    }

private:
    TimeSeriesChart chart;
};

class MagneticFieldBarPlot {
public:
    MagneticFieldBarPlot()
    {
        style = MagneticChartStyle();
        style.showLegend = false;
        chart.SetStyle(style);
        chart.SetAxisTitles("", "A");
        chart.SetValueRange(0.0f, 1000.0f);
    }

    void SetData(const std::string& title,
                 const std::vector<std::string>& labels,
                 const std::vector<float>& values)
    {
        channelLabels = labels;
        channelValues = values;
        chart.SetTitle(title);

        DataTable data;
        data.columnNames = { "Channel", "Actual" };
        for (std::size_t index = 0; index < values.size(); ++index) {
            data.rows.push_back({ static_cast<float>(index), values[index] });
        }
        chart.SetData(data);
    }

    void Render(int width, int height)
    {
        const int safeWidth = std::max(width, 1);
        const int safeHeight = std::max(height, 1);
        PrepareViewport(safeWidth, safeHeight);
        chart.Render({ 0.0f, 0.0f, static_cast<float>(safeWidth), static_cast<float>(safeHeight) });
        DrawChannelLabels(static_cast<float>(safeWidth), static_cast<float>(safeHeight));
    }

private:
    void DrawChannelLabels(float width, float height)
    {
        if (channelLabels.empty()) return;

        const float plotLeft = style.leftMargin;
        const float plotRight = std::max(width - style.plotPadding, style.leftMargin + 1.0f);
        const float plotBottom = style.bottomMargin;
        const float plotTop = std::max(height - style.titleMargin, style.bottomMargin + 1.0f);
        const float slotWidth = (plotRight - plotLeft) / static_cast<float>(channelLabels.size());
        constexpr float maximum = 1000.0f;

        for (std::size_t index = 0; index < channelLabels.size(); ++index) {
            const float centerX = plotLeft + (static_cast<float>(index) + 0.5f) * slotWidth;
            font_renderer::DrawText(channelLabels[index], centerX, plotBottom - 24.0f, 15.0f,
                                    false, style.textColor, 1.0f, style.fontPath);
            if (index >= channelValues.size()) continue;
            const float amount = std::clamp(channelValues[index] / maximum, 0.0f, 1.0f);
            const float valueY = plotBottom + amount * (plotTop - plotBottom);
            font_renderer::DrawText(FormatOneDecimal(channelValues[index]),
                                    centerX,
                                    std::min(plotTop - 12.0f, valueY + 17.0f),
                                    15.0f, false, style.textColor, 1.0f, style.fontPath);
        }
        font_renderer::DrawText("Channel", (plotLeft + plotRight) * 0.5f, 16.0f, 15.0f,
                                false, style.textColor, 1.0f, style.fontPath);
    }

    BarChart chart;
    ChartStyle style;
    std::vector<std::string> channelLabels;
    std::vector<float> channelValues;
};

class MagneticFieldLinePlot {
public:
    MagneticFieldLinePlot()
    {
        ChartStyle style = MagneticChartStyle();
        style.showPoints = false;
        style.showLineShadow = false;
        style.showLegend = true;
        chart.SetStyle(style);
        chart.SetMaximumPoints(kMagneticVisibleSamples);
        chart.SetAxisTitles("Time (s)", "A");
    }

    void SetData(const std::string& title,
                 const std::vector<std::string>& labels,
                 const std::vector<std::vector<float>>& samples)
    {
        DataTable data;
        data.columnNames = { "Time" };
        data.columnNames.insert(data.columnNames.end(), labels.begin(), labels.end());
        data.rows = samples;
        if (!data.rows.empty()) {
            const float start = data.rows.front().front();
            for (auto& row : data.rows) {
                if (!row.empty()) row.front() -= start;
            }
        }
        chart.SetTitle(title);
        chart.SetData(data);
    }

    void Render(int width, int height)
    {
        const int safeWidth = std::max(width, 1);
        const int safeHeight = std::max(height, 1);
        PrepareViewport(safeWidth, safeHeight);
        chart.Render({ 0.0f, 0.0f, static_cast<float>(safeWidth), static_cast<float>(safeHeight) });
    }

private:
    TimeSeriesChart chart;
};
} // namespace

void BindEngine(py::module_& module)
{
    py::class_<Engine>(module, "Engine")
        .def(py::init<>())
        .def("initialize", &Engine::Initialize)
        .def("Update", &Engine::Update)
        .def("Render", &Engine::Render);

    module.def("load_opengl", [](const py::function& getProcAddress) {
        currentGetProcAddress = &getProcAddress;
        try {
            Renderer::LoadOpenGL(&PythonGetProcAddress);
        } catch (...) {
            currentGetProcAddress = nullptr;
            throw;
        }
        currentGetProcAddress = nullptr;
    });

    py::class_<MagneticFieldSpeedometer>(module, "MagneticFieldSpeedometer")
        .def(py::init<>())
        .def("set_values", &MagneticFieldSpeedometer::SetValues,
             py::arg("target_value"), py::arg("actual_value"),
             py::arg("maximum_value"), py::arg("channel_name"))
        .def("set_status", &MagneticFieldSpeedometer::SetStatus,
             py::arg("converged"), py::arg("error"),
             py::arg("tolerance"), py::arg("convergence_seconds"),
             py::arg("timing_active"))
        .def("render", &MagneticFieldSpeedometer::Render,
             py::arg("width"), py::arg("height"));

    py::class_<TimeDomainLinePlot>(module, "TimeDomainLinePlot")
        .def(py::init<>())
        .def("set_samples", &TimeDomainLinePlot::SetSamples, py::arg("samples"))
        .def("render", &TimeDomainLinePlot::Render, py::arg("width"), py::arg("height"));

    py::class_<MagneticFieldBarPlot>(module, "MagneticFieldBarPlot")
        .def(py::init<>())
        .def("set_data", &MagneticFieldBarPlot::SetData,
             py::arg("title"), py::arg("labels"), py::arg("values"))
        .def("render", &MagneticFieldBarPlot::Render, py::arg("width"), py::arg("height"));

    py::class_<MagneticFieldLinePlot>(module, "MagneticFieldLinePlot")
        .def(py::init<>())
        .def("set_data", &MagneticFieldLinePlot::SetData,
             py::arg("title"), py::arg("labels"), py::arg("samples"))
        .def("render", &MagneticFieldLinePlot::Render, py::arg("width"), py::arg("height"));
}
