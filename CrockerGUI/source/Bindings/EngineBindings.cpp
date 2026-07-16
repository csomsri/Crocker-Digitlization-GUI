#include "Bindings.hpp"

#include "Engine/Engine.hpp"
#include "Engine/Render/Renderer.hpp"
#include "Engine/Viz/Gauges/MagneticFieldSpeedometer.hpp"

#include <cstdint>

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
}
