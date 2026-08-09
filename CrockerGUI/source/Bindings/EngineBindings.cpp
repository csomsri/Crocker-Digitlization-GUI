#include "Bindings.hpp"

#include "Engine/Engine.hpp"
#include "Engine/Render/Renderer.hpp"
#include "Engine/Viz/Charts/ChartTypes/TimeSeriesChart.hpp"
#include "Engine/Viz/Gauges/MagneticFieldSpeedometer.hpp"

#include <pybind11/stl.h>

#include <algorithm>
#include <cstdint>
#include <vector>

namespace py = pybind11;

namespace {
thread_local const py::function* currentGetProcAddress = nullptr;

void* PythonGetProcAddress(const char* name)
{
    if (currentGetProcAddress == nullptr) return nullptr;
    py::gil_scoped_acquire gil;
    const py::object result = (*currentGetProcAddress)(name);
    if (result.is_none()) return nullptr;
    return reinterpret_cast<void*>(result.cast<std::uintptr_t>());
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
        chart.SetMaximumPoints(240);
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
}
