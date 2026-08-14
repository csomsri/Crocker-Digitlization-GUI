from __future__ import annotations

import json
import base64
import sys
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)
from PySide6.QtWidgets import QApplication


def draw_pdf(manifest_source: str) -> None:
    if manifest_source == "-":
        manifest = json.loads(sys.stdin.read())
    else:
        manifest = json.loads(Path(manifest_source).read_text(encoding="utf-8"))
    output_path = str(manifest["output_path"])
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    header_text = str(manifest["header_text"])
    image_data = [str(data) for data in manifest.get("image_data", [])]
    image_paths = [str(path) for path in manifest.get("image_paths", [])]
    color_mode = str(manifest.get("color_mode", "normal"))
    marker_x_ratios = [
        float(ratio)
        for ratio in manifest.get("marker_x_ratios", [])
    ]

    writer = QPdfWriter(output_path)
    writer.setResolution(144)
    writer.setPageLayout(
        QPageLayout(
            QPageSize(QPageSize.PageSizeId.Letter),
            QPageLayout.Orientation.Landscape,
            QMarginsF(0.35, 0.35, 0.35, 0.35),
            QPageLayout.Unit.Inch,
        )
    )

    painter = QPainter()
    if not painter.begin(writer):
        raise RuntimeError("Could not create the PDF file.")
    try:
        page = QRectF(0.0, 0.0, float(writer.width()), float(writer.height()))
        draw_page(
            painter,
            page,
            header_text,
            image_data,
            image_paths,
            color_mode,
            marker_x_ratios,
        )
    finally:
        painter.end()


def draw_page(
    painter: QPainter,
    page: QRectF,
    header_text: str,
    image_data: list[str],
    image_paths: list[str],
    color_mode: str,
    marker_x_ratios: list[float],
) -> None:
    painter.fillRect(page, QColor("#ffffff"))
    side_margin = page.width() * 0.045
    content = page.adjusted(side_margin, 0.0, -side_margin, 0.0)
    header = QRectF(content.left(), content.top(), content.width(), page.height() * 0.115)

    title_font = QFont()
    title_font.setPointSize(16)
    title_font.setBold(True)
    body_font = QFont()
    body_font.setPointSize(10)

    painter.setFont(title_font)
    painter.setPen(QColor("#111827"))
    painter.drawText(
        QRectF(header.left(), header.top(), header.width(), header.height() * 0.55),
        Qt.AlignLeft | Qt.AlignVCenter,
        "Database History Plots",
    )
    painter.setFont(body_font)
    painter.drawText(
        QRectF(
            header.left(),
            header.top() + header.height() * 0.45,
            header.width(),
            header.height() * 0.42,
        ),
        Qt.AlignLeft | Qt.AlignVCenter,
        header_text,
    )
    painter.setPen(QPen(QColor("#111827"), 1.4))
    painter.drawLine(QPointF(content.left(), header.bottom()), QPointF(content.right(), header.bottom()))

    gap = 0.0
    plot_top = header.bottom() + gap * 2
    plot_area = QRectF(
        content.left(),
        plot_top,
        content.width(),
        page.bottom() - plot_top,
    )
    painter.fillRect(plot_area, QColor("#ffffff" if color_mode in {"bw", "limited"} else "#0f172a"))

    plot_count = max(1, len(image_data) or len(image_paths))
    plot_height = (plot_area.height() - gap * (plot_count - 1)) / plot_count
    for index, image in enumerate(load_images(image_data, image_paths)):
        if image.isNull():
            continue
        target = QRectF(
            plot_area.left(),
            plot_area.top() + index * (plot_height + gap),
            plot_area.width(),
            plot_height,
        )
        painter.drawImage(target, image, QRectF(image.rect()))
    draw_marker_connectors(painter, plot_area, marker_x_ratios, color_mode)
    draw_plot_area_border(painter, plot_area, color_mode)


def draw_marker_connectors(
    painter: QPainter,
    plot_area: QRectF,
    marker_x_ratios: list[float],
    color_mode: str,
) -> None:
    if not marker_x_ratios:
        return
    color = QColor("#111827" if color_mode in {"bw", "limited"} else "#cbd5e1")
    painter.setPen(QPen(color, 1.2, Qt.DashLine))
    for ratio in marker_x_ratios:
        x = plot_area.left() + plot_area.width() * max(0.0, min(1.0, ratio))
        painter.drawLine(QPointF(x, plot_area.top()), QPointF(x, plot_area.bottom()))


def draw_plot_area_border(painter: QPainter, plot_area: QRectF, color_mode: str) -> None:
    color = QColor("#111827" if color_mode in {"bw", "limited"} else "#94a3b8")
    painter.setPen(QPen(color, 1.2, Qt.SolidLine))
    painter.drawLine(plot_area.topLeft(), plot_area.topRight())
    painter.drawLine(plot_area.bottomLeft(), plot_area.bottomRight())
    painter.drawLine(plot_area.topLeft(), plot_area.bottomLeft())
    painter.drawLine(plot_area.topRight(), plot_area.bottomRight())


def load_images(image_data: list[str], image_paths: list[str]) -> list[QImage]:
    images = []
    if image_data:
        for encoded in image_data:
            image = QImage()
            image.loadFromData(base64.b64decode(encoded), "PNG")
            images.append(image)
        return images
    return [QImage(path) for path in image_paths]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: export_history_pdf.py <manifest.json|->", file=sys.stderr)
        return 2
    app = QApplication.instance() or QApplication([])
    try:
        draw_pdf(argv[1])
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
