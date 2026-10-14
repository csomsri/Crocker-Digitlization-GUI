"""Shared graphite palette, including compatibility for older page styles."""
import re

BACKGROUND = '#111214'
PANEL = '#1a1c1f'
CONTROL = '#23262a'
BORDER = '#33363b'
TEXT = '#f3f3f4'
MUTED = '#a5a8ae'
ACCENT = '#e82138'

# Resolve older named-widget rules too: an appended generic rule cannot
# override their higher selector specificity. Alarm and signal colors stay intact.
LEGACY_COLORS = {
    '#0b1120': BACKGROUND, '#0f172a': BACKGROUND, '#111827': PANEL,
    '#101a29': PANEL, '#101d2d': PANEL, '#132236': PANEL,
    '#142235': CONTROL, '#172033': CONTROL, '#17243a': CONTROL,
    '#1e293b': CONTROL, '#1b2c42': CONTROL, '#203247': BORDER,
    '#334155': BORDER, '#34465d': BORDER, '#344357': BORDER,
    '#475569': '#41444a', '#40516b': '#41444a', '#64748b': '#80858e',
    '#94a3b8': MUTED, '#cbd5e1': '#c4c7cc', '#e5e7eb': '#e6e7e9',
    '#dbeafe': TEXT, '#eff6ff': TEXT, '#bfdbfe': '#c4c7cc',
    '#2563eb': ACCENT, '#1d4ed8': '#bd1d30', '#1e40af': '#6e2932',
    '#3b82f6': ACCENT, '#60a5fa': '#e6e7e9', '#93c5fd': '#c4c7cc',
    '#1e3a8a': '#3b252c', '#172236': PANEL, '#24344e': CONTROL,
    '#183b78': '#373a40', '#131f30': PANEL, '#1a2a40': CONTROL,
    '#192a40': BACKGROUND, '#213954': '#36383d', '#2b3b51': BORDER,
    '#3a4d66': '#41444a', '#2c496a': '#303338', '#48668b': '#41444a',
    '#19354a': CONTROL, '#31546d': '#41444a', '#293b52': BORDER,
    '#182638': '#1c1e22', '#477fed': ACCENT, '#3473f2': '#ff3b50',
    '#59b9f3': ACCENT, '#91d8ff': TEXT, '#80b4ff': '#c4c7cc',
    '#0b1220': PANEL, '#080d1b': BACKGROUND, '#111b2e': PANEL,
    '#111e30': PANEL, '#243e60': CONTROL, '#23354c': CONTROL,
    '#28639a': '#36383d', '#162337': '#1c1e22', '#1c324c': CONTROL,
    '#223b56': CONTROL, '#1b2b40': PANEL, '#315477': '#36383d',
    '#24364c': CONTROL, '#152238': BACKGROUND, '#254b78': '#36383d',
    '#1b2d47': CONTROL, '#1e324d': CONTROL, '#111c30': BACKGROUND,
    '#29466a': '#36383d', '#17263c': PANEL, '#315d8b': '#41444a',
    '#1d3048': CONTROL, '#294560': '#36383d', '#172335': PANEL,
    '#3c5775': '#41444a', '#5b7da3': '#858a94', '#20334b': CONTROL,
    '#0e151a': BACKGROUND, '#080d11': BACKGROUND, '#0a1014': BACKGROUND,
    '#3a4851': '#41444a', '#11191f': PANEL, '#172129': CONTROL,
    '#20303b': CONTROL, '#93a9c5': MUTED, '#8fa5c2': MUTED,
}
_HEX = re.compile(r'#[0-9a-fA-F]{6}\b')
_RGBA = re.compile(r'rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(\s*,\s*[\d.]+)?\s*\)')


def graphite_stylesheet(stylesheet: str) -> str:
    """Normalize legacy theme declarations, retaining opacity and state colors."""
    def rgba(match):
        original = '#%02x%02x%02x' % tuple(int(match[i]) for i in (1, 2, 3))
        replacement = LEGACY_COLORS.get(original)
        if replacement is None:
            return match[0]
        values = [str(int(replacement[i:i+2], 16)) for i in (1, 3, 5)]
        return ('rgba(' if match[4] else 'rgb(') + ', '.join(values) + (match[4] or '') + ')'
    stylesheet = _RGBA.sub(rgba, stylesheet)
    return _HEX.sub(lambda match: LEGACY_COLORS.get(match[0].lower(), match[0]), stylesheet)
