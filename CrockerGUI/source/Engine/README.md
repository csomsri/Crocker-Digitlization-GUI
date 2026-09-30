# Graphics engine structure

The engine is a drawing library hosted by Qt. Qt owns the event loop, native
OpenGL contexts, and widgets. Control-system execution remains under `Controls`.

Public headers live in `include/Engine`; implementations mirror that structure
under `source/Engine`:

```text
Engine/
  Core/                 Color, Rect, Point, Viewport
  Graphics/             RenderContext, Canvas2D, DrawList
    OpenGL/             Private buffer/VAO/texture handles, shaders, state guard
  Text/                 FontManager, TextStyle, TextLayout, TextRenderer
    Internal/           FontRasterizer and GlyphAtlas implementations
  Visualization/
    Data/               DataTable
    Charts/             Chart types, axis/legend layout, tick formatting
    Gauges/             MagneticFieldSpeedometer and GaugeStyle
    Plots/              Application-facing magnetic-field plot adapters
```

The `OpenGL` and `Internal` directories are implementation-only; public text,
chart, and graphics headers do not include OpenGL or Qt. `Objects.hpp` groups
the small private buffer/VAO/texture handles rather than creating an otherwise
empty source file for each handle.

The triangle renderer, camera, and its original wrappers now live in
`examples/Triangle`, compiled only with `CROCKER_BUILD_OPENGL_TEST`. The former
empty `Engine` loop is removed from the C++ engine. Its existing Python facade
remains a no-op compatibility object. The plot classes have moved out of
`EngineBindings.cpp`; bindings now translate arguments and expose methods.
Chart-specific notes live in `docs/Engine/Charts`.

## Text pipeline

1. `FontManager` loads and caches font faces by path. Font IDs belong to that
   manager and remain valid across GPU resource release/recreation.
2. `FontRasterizer` isolates the bundled Nuklear font baker. It produces CPU
   glyph metrics and coverage images; no context is required.
3. `TextLayout` decodes UTF-8 and produces positioned glyphs. It handles
   proportional advances, baselines, left/center/right alignment, multiline
   text, tabs, and an explicit missing-glyph count.
4. `Canvas2D` queues text runs. `TextRenderer` uploads their geometry together
   and batches adjacent glyphs using the same atlas texture. Primitive draws
   flush queued text first, preserving the original drawing order.
5. `GlyphAtlas` lazily uploads each font's baked coverage page for this context.
   Multiple fonts coexist; changing fonts does not replace another font's atlas.

The default baked repertoire covers Latin, Greek, a small arrow set, and the
replacement character, including `µ`, `°`, `±`, and `Δ` when the face provides
them. `FontManager::SetFallbacks` supplies a fallback chain. Unsupported
codepoints become one replacement glyph per decoded codepoint. This is not a
complex-script shaping engine; kerning, bidirectional shaping, dynamic Unicode
page expansion, and automatic line wrapping remain future extensions.

Text sizes and positions use logical pixels. `Viewport` carries framebuffer
dimensions and device-pixel ratio. The Python widgets pass their pixel ratio
to native `render(width, height, pixel_ratio)`, whose first two arguments remain
framebuffer dimensions. Existing two-argument calls still mean pixel ratio 1.
Chart areas use viewport-local logical coordinates with a bottom-left origin.

`LineChart` uses the same measured advances for legend layout and rendering;
the character-count width approximation has been removed. `TextStyle` controls
rotation, color, opacity, and shadow. `GaugeStyle` exposes font and text scaling.
Shaders live under `assets/shaders`, with compiler/linker diagnostics including
the shader name.

## Context ownership and lifetime

Each chart or gauge owns a `RenderContext`. The first draw attaches its GPU
objects to the host-announced native context identity. Drawing or releasing in
a different context is rejected. Context identity is thread-local; textures,
programs, fonts, and buffers are not stored in a process-wide mutable singleton.
The initial implementation uses separate resources even for Qt share groups.

`NativeRenderLifecycle.py` makes the owning Qt context current before calling
`release_resources()`. It connects to `aboutToBeDestroyed` and handles explicit
widget close. Release is idempotent; a later paint recreates GPU objects from
the retained CPU data. Destructors never issue GL calls, because Qt/Python may
destroy C++ objects after their context has already disappeared. Standalone C++
hosts must similarly call `ReleaseResources`/`RenderContext::Release` while
current, before destroying the native context.

For custom hosts:

```cpp
// After making the native context current and loading GL functions:
RenderContext::SetCurrentContext(nativeContextIdentity);
context.SetPixelRatio(devicePixelRatio);
canvas.BeginFrame();
auto style = TextStyle{};
style.font = context.Fonts().Load(fontPath);
auto run = TextLayout(context.Fonts()).Layout("Current (µA)", style);
canvas.DrawText(run, {120, 30});
canvas.Flush();
// At context teardown, while still current:
context.Release();
RenderContext::SetCurrentContext(0);
```

Text runs must be used with the font manager that produced them. Fonts/managers
and drawing contexts are single-render-thread objects. The text and primitive
passes restore the GL bindings, blending, and other state they change. Texture
uploads restore pixel-unpack settings. Existing scissor clipping is respected;
flush before changing external clipping/state or switching contexts. Widget
frame setup intentionally sets the viewport and clears its framebuffer.

## Verification

- `TextLayoutTest`: CPU-only UTF-8, scientific glyphs, fallback, proportional
  measurements, alignment, multiline layout, font caching, and tick/legend layout.
- `tests/EngineRenderingTest.py`: real offscreen OpenGL, independent contexts,
  Unicode labels, 1×/2× DPI, context misuse rejection, GL state restoration, and
  GPU resource release/recreation. Saves images in `build/engine-rendering`.
- `tests/NativeWidgetLifecycleTest.py`: real Qt native widgets, shared contexts,
  repaint after cleanup, close/reopen, and widget destruction.
- `tests/PlotRenderingTest.py --native`: application chart rendering and layout.

Run the native Python checks after rebuilding `CycloViz`. They require a working
OpenGL 4.6 driver, and use offscreen surfaces or hidden widgets rather than live
hardware. The existing CTest control/sequence checks remain independent.
