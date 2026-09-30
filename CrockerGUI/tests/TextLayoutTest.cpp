#include "Engine/Text/TextLayout.hpp"
#include "Engine/Visualization/Charts/TickFormatter.hpp"
#include "Engine/Visualization/Charts/LegendLayout.hpp"
#include <cmath>
#include <iostream>
#include <stdexcept>
using namespace crocker::engine;
void Check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
int main() {
    try {
        FontManager fonts;
        const auto font = fonts.Load();
        Check(font == fonts.Load(), "Repeated font load should be cached");
        TextLayout layout(fonts);
        TextStyle style; style.font = font; style.size = 20;
        auto narrow = layout.Layout("iii", style);
        auto wide = layout.Layout("WWW", style);
        Check(wide.advance > narrow.advance * 1.5f, "Use measured proportional advances");
        Check(std::abs(wide.bounds.x + wide.advance / 2) < .001f, "Centered alignment");
        auto symbols = layout.Layout("\xc2\xb5\xc2\xb0\xc2\xb1\xce\x94", style);
        Check(symbols.glyphs.size() == 4, "Decode codepoints, not UTF-8 bytes");
#ifdef _WIN32
        Check(symbols.missingGlyphs == 0, "Default font must render scientific symbols");
#endif
        auto missing = layout.Layout("\xf0\x9f\x9a\x80", style);
        Check(missing.glyphs.size() == 1 && missing.missingGlyphs == 1, "One replacement per unsupported codepoint");
        Check(TextLayout::DecodeUtf8("\xed\xa0\x80")[0] == U'\ufffd', "Reject surrogate UTF-8");
        Check(TextLayout::DecodeUtf8("\xf4\x90\x80\x80")[0] == U'\ufffd', "Reject out-of-range UTF-8");
        Check(TextLayout::DecodeUtf8("\xe2\x82")[0] == U'\ufffd', "Reject truncated UTF-8");
        auto one = layout.Layout("100 A", style);
        auto lines = layout.Layout("100 A\n100 A", style);
        Check(lines.bounds.height > one.bounds.height, "Multiline metrics");
        Check(std::abs(lines.advance - one.advance) < .001f, "Multiline width is longest line");
        auto spaced = layout.Layout("A A", style);
        Check(spaced.advance > layout.Layout("AA", style).advance, "Spaces have advances");
        auto tabbed = layout.Layout("A\tA", style);
        Check(tabbed.advance > spaced.advance, "Tabs advance to stops");
        style.horizontalAlignment = HorizontalAlignment::Left;
        style.verticalAlignment = VerticalAlignment::Baseline;
        auto left = layout.Layout("100 A", style);
        Check(left.bounds.x == 0, "Left alignment");
        style.size = 40;
        auto twice = layout.Layout("100 A", style);
        Check(std::abs(twice.advance - 2 * left.advance) < .001f, "Logical size scales consistently");
        bool rejected = false;
        try { fonts.Load("does-not-exist.ttf"); } catch (const std::exception&) { rejected = true; }
        Check(rejected, "Missing font must produce an actionable failure");
        Check(TickFormatter::Format(-0.000001f, 10) == "0", "No negative zero ticks");
        LegendLayout legend({20, 30, 40});
        Check(legend.offsets[2] == 50 && legend.totalWidth == 90, "Legend prefix layout");
        std::cout << "CPU-only text layout, UTF-8, font cache, alignment and metrics passed\n";
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
