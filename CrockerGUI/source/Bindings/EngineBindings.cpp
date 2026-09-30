#include "Bindings.hpp"

#include "Engine/Visualization/Plots/FieldPlots.hpp"
#include "Engine/Graphics/RenderContext.hpp"
using namespace crocker::engine;

#include "Engine/Visualization/Charts/BarChart.hpp"
#include "Engine/Visualization/Charts/TimeSeriesChart.hpp"

#include "Engine/Visualization/Gauges/MagneticFieldSpeedometer.hpp"

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
// Compatibility for the former empty Engine facade. Qt owns the actual loop.
class Engine {
public:
    void Initialize() {}
    void Update() {}
    void Render() {}
};

void* PythonGetProcAddress(const char* name)
{
    if (currentGetProcAddress == nullptr) return nullptr;
    py::gil_scoped_acquire gil;
    const py::object result = (*currentGetProcAddress)(name);
    if (result.is_none()) return nullptr;
    return reinterpret_cast<void*>(result.cast<std::uintptr_t>());
}

} // namespace

void BindEngine(py::module_& module)
{
    py::class_<Engine>(module, "Engine")
        .def(py::init<>())
        .def("initialize", &Engine::Initialize)
        .def("Update", &Engine::Update)
        .def("Render", &Engine::Render);

    module.def("set_current_render_context", &RenderContext::SetCurrentContext);

    module.def("load_opengl", [](const py::function& getProcAddress) {
        currentGetProcAddress = &getProcAddress;
        try {
            RenderContext::LoadOpenGL(&PythonGetProcAddress);
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
        .def("release_resources", &MagneticFieldSpeedometer::ReleaseResources)
        .def("render", &MagneticFieldSpeedometer::Render,
             py::arg("width"), py::arg("height"), py::arg("pixel_ratio") = 1.0f);

    py::class_<TimeDomainLinePlot>(module, "TimeDomainLinePlot")
        .def(py::init<bool>(), py::arg("coil_response") = false)
        .def("set_samples", &TimeDomainLinePlot::SetSamples, py::arg("samples"))
        .def("release_resources", &TimeDomainLinePlot::ReleaseResources)
        .def("render", &TimeDomainLinePlot::Render, py::arg("width"), py::arg("height"), py::arg("pixel_ratio") = 1.0f);

    py::class_<MagneticFieldBarPlot>(module, "MagneticFieldBarPlot")
        .def(py::init<>())
        .def("set_data", &MagneticFieldBarPlot::SetData,
             py::arg("title"), py::arg("labels"), py::arg("values"))
        .def("release_resources", &MagneticFieldBarPlot::ReleaseResources)
        .def("render", &MagneticFieldBarPlot::Render, py::arg("width"), py::arg("height"), py::arg("pixel_ratio") = 1.0f);

    py::class_<MagneticFieldLinePlot>(module, "MagneticFieldLinePlot")
        .def(py::init<>())
        .def("set_data", &MagneticFieldLinePlot::SetData,
             py::arg("title"), py::arg("labels"), py::arg("samples"))
        .def("release_resources", &MagneticFieldLinePlot::ReleaseResources)
        .def("render", &MagneticFieldLinePlot::Render, py::arg("width"), py::arg("height"), py::arg("pixel_ratio") = 1.0f);
}
