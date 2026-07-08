#include "Bindings/Bindings.hpp"

#include "Engine/Engine.hpp"

namespace py = pybind11;

void BindEngine(py::module_& module)
{
    py::class_<Engine>(module, "Engine")
        .def(py::init<>())
        .def("initialize", &Engine::Initialize)
        .def("Update", &Engine::Update)
        .def("Render", &Engine::Render);
}
